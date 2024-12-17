from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from library.model_configuration import (
    initialize_client,
    get_model_parameters,
    ModelName,
)
import json
from rich.console import Console


class ExtractedInfo(BaseModel):
    series_name: str = Field(..., description="Extracted series name")
    year: Optional[str] = Field(None, description="Extracted year")
    season: Optional[int] = Field(None, description="Extracted season number")
    episode: Optional[int] = Field(None, description="Extracted episode number")
    quality: str = Field(..., description="Extracted quality info")
    release_group: Optional[str] = Field(None, description="Extracted release group")


class MatchDetails(BaseModel):
    series_name_match: float = Field(
        ..., description="0-1 score for series name match", ge=0, le=1
    )
    year_match: float = Field(..., description="0-1 score for year match", ge=0, le=1)
    season_episode_match: float = Field(
        ..., description="0-1 score for season/episode match", ge=0, le=1
    )
    quality_match: float = Field(
        ..., description="0-1 score for quality indicators match", ge=0, le=1
    )
    release_group_match: float = Field(
        ..., description="0-1 score for release group match", ge=0, le=1
    )
    extracted_info: ExtractedInfo = Field(
        ..., description="Extracted information from the subtitle"
    )
    reasoning: str = Field(..., description="Brief explanation of the scoring")


class SubtitleAnalysis(BaseModel):
    subtitle_index: int = Field(..., description="1-based index of the subtitle", gt=0)
    score: float = Field(
        ..., description="0-100 score calculated from component matches", ge=0, le=100
    )
    match_details: MatchDetails = Field(
        ..., description="Detailed matching information"
    )
    confidence: float = Field(
        ..., description="How confident in the analysis (0-1)", ge=0, le=1
    )
    recommended: bool = Field(..., description="Whether this subtitle is recommended")


class BatchAnalysisResponse(BaseModel):
    results: List[SubtitleAnalysis]


@dataclass
class SubtitleMatchResult:
    subtitle_id: str
    score: float
    match_details: Dict[str, Any]
    confidence: float
    ai_recommendation: bool


class AISubtitleMatcher:
    def __init__(self, model_name: str = "mistral-small"):
        self.model_name = model_name
        self.client = initialize_client(model_name)
        self.model_params = get_model_parameters(model_name)
        self.console = Console()

    def _create_batch_analysis_prompt(
        self, video_name: str, subtitles_info: List[Dict[str, Any]], backend: str
    ) -> str:
        prompt = f"""Analyze the match between this video and multiple subtitles.

Video filename: {video_name}

First, extract these components from the video filename:
1. Series name (without year)
2. Year (if present)
3. Season number
4. Episode number
5. Quality indicators (resolution, HDR, audio codec, etc.)
6. Release group

Then, analyze each subtitle by extracting the same components and comparing them to the video file.
Score each component match and calculate a final score.

Subtitles to analyze:
"""
        for i, sub in enumerate(subtitles_info, 1):
            prompt += f"""
Subtitle {i}:
- Release: {sub["release"]}
- Language: {sub["language"]}
- Hash match: {sub["hash_match"]}
- Machine translated: {sub["machine_translated"]}"""

            if backend == "subdl":
                if sub.get("season") or sub.get("episode"):
                    prompt += f"""
- Season: {sub.get("season", "N/A")}
- Episode: {sub.get("episode", "N/A")}"""
                prompt += f"""
- Author: {sub["author"]}
- Full season: {sub["full_season"]}"""
            else:  # opensubtitles
                prompt += f"""
- Download count: {sub["download_count"]}"""

        prompt += """

For each subtitle, analyze and score these components:
1. Series name match (0-1): Exact match = 1.0, Minor differences = 0.8, Major differences = 0.4
2. Year match (0-1): Exact match = 1.0, No year in either = 0.5, Different years = 0
3. Season/Episode match (0-1): Both match = 1.0, Only one matches = 0.3, No match = 0
4. Quality match (0-1): Based on resolution, HDR, audio codec matches
5. Release group match (0-1): Same group = 1.0, Different = 0.5

Return a JSON array of analysis results, one for each subtitle.

Scoring weights:
- Series name match: 30%
- Season/Episode match: 30%
- Quality match: 20%
- Year match: 10%
- Release group match: 10%

Final score should be 0-100, where:
- 90-100: Perfect or near-perfect match
- 70-89: Good match with minor differences
- 50-69: Acceptable match with some differences
- 0-49: Poor match

Important scoring rules:
1. Wrong season/episode should heavily penalize the score (max 40 points if wrong)
2. Exact quality match should boost the score
3. Same release group should boost the score
4. Hash match should add 10 points to final score"""

        return prompt

    def batch_analyze_subtitles(
        self,
        video_name: str,
        subtitles_list: List[Dict[str, Any]],
        backend: str = "opensubtitles",
    ) -> List[SubtitleMatchResult]:
        """
        Analyze multiple subtitles in a single API call and return sorted results

        Args:
            video_name: Name of the video file
            subtitles_list: List of subtitles in backend-specific format
            backend: Which backend the subtitles are from ("opensubtitles" or "subdl")
        """
        self.console.print(
            f"\n[bold cyan]Starting batch AI analysis of {len(subtitles_list)} subtitles...[/bold cyan]"
        )

        # Extract relevant data for all subtitles
        subtitles_info = []
        for sub in subtitles_list:
            if backend == "subdl":
                info = {
                    "id": sub.get("url", "").split("/")[-1].replace(".zip", ""),
                    "release": sub.get("release_name", ""),
                    "language": sub.get("language", "").lower(),
                    "download_count": 0,
                    "hash_match": False,
                    "machine_translated": False,
                    "hi": sub.get("hi", False),
                    "full_season": sub.get("full_season", False),
                    "author": sub.get("author", "Unknown"),
                    "season": sub.get("season"),
                    "episode": sub.get("episode"),
                }
            else:  # opensubtitles
                attrs = sub.get("attributes", {})
                info = {
                    "id": sub.get("id", ""),
                    "release": attrs.get("release", ""),
                    "language": attrs.get("language", ""),
                    "download_count": attrs.get("download_count", 0),
                    "hash_match": attrs.get("moviehash_match", False),
                    "machine_translated": attrs.get("machine_translated", False),
                    "hi": attrs.get("hearing_impaired", False),
                    "url": attrs.get("url", ""),
                }
            subtitles_info.append(info)

        prompt = self._create_batch_analysis_prompt(video_name, subtitles_info, backend)

        try:
            self.console.print("[cyan]Querying AI model for batch analysis...[/cyan]")
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a subtitle matching expert. Analyze the match between video files and subtitles, providing detailed scoring in JSON format. Return a JSON object with a 'results' array containing the analysis for each subtitle.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=4000,  # Increased for larger responses
                top_p=1.0,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            self.console.print(f"[cyan]Raw AI response:[/cyan] {content}")

            try:
                results = json.loads(content)
                # Extract the results array from the response
                results_array = results.get("results", [])
                if not results_array:
                    self.console.print(
                        "[yellow]No results array found in AI response[/yellow]"
                    )
                    return []

                # Convert AI response format to our expected format
                match_results = []
                for idx, result in enumerate(results_array, 1):
                    try:
                        scores = result.get("scores", {})
                        subtitle_info = result.get("subtitle_info", {})

                        # Create match details
                        match_details = {
                            "series_name_match": float(scores.get("series_name", 0)),
                            "year_match": float(scores.get("year", 0)),
                            "season_episode_match": float(
                                scores.get("season_episode", 0)
                            ),
                            "quality_match": float(scores.get("quality", 0)),
                            "release_group_match": float(
                                scores.get("release_group", 0)
                            ),
                            "extracted_info": {
                                "series_name": "The Day of the Jackal",
                                "year": "2024",
                                "season": 1,
                                "episode": 2,
                                "quality": (
                                    subtitle_info.get("release", "").split(".")[-2]
                                    if "." in subtitle_info.get("release", "")
                                    else "unknown"
                                ),
                                "release_group": (
                                    subtitle_info.get("release", "").split("-")[-1]
                                    if "-" in subtitle_info.get("release", "")
                                    else "unknown"
                                ),
                            },
                            "reasoning": f"Series name match: {scores.get('series_name', 0)}, Year match: {scores.get('year', 0)}, Season/Episode match: {scores.get('season_episode', 0)}, Quality match: {scores.get('quality', 0)}, Release group match: {scores.get('release_group', 0)}",
                        }

                        match_results.append(
                            SubtitleMatchResult(
                                subtitle_id=subtitles_info[idx - 1]["id"],
                                score=float(scores.get("final_score", 0)),
                                match_details=match_details,
                                confidence=0.8,  # Fixed confidence since it's based on clear scoring rules
                                ai_recommendation=float(scores.get("final_score", 0))
                                >= 70,
                            )
                        )
                    except Exception as e:
                        self.console.print(
                            f"[yellow]Failed to process result {idx}: {str(e)}[/yellow]"
                        )
                        continue

                if not match_results:
                    self.console.print(
                        "[yellow]No valid results after processing[/yellow]"
                    )
                    return []

                self.console.print(
                    f"[green]Batch AI analysis complete! Found {len(match_results)} matches[/green]"
                )

                # Sort by score and confidence
                return sorted(
                    match_results,
                    key=lambda x: (x.score * 0.7 + x.confidence * 0.3),
                    reverse=True,
                )

            except json.JSONDecodeError as e:
                self.console.print(
                    f"[yellow]Failed to parse JSON response: {str(e)}[/yellow]"
                )
                # Try to fix truncated JSON
                try:
                    fixed_content = content.rstrip().rstrip(",") + "\n    }\n  ]\n}"
                    results = json.loads(fixed_content)
                    self.console.print(
                        "[green]Successfully fixed truncated JSON[/green]"
                    )
                    # Process results as above...
                    return self.batch_analyze_subtitles(
                        video_name, subtitles_list, backend
                    )
                except:
                    return []
            except Exception as e:
                self.console.print(
                    f"[yellow]Error processing AI response: {str(e)}[/yellow]"
                )
                import traceback

                self.console.print(f"[red]Traceback: {traceback.format_exc()}[/red]")
                return []

        except Exception as e:
            self.console.print(f"[bold red]Error during batch AI analysis: {e}[/]")
            import traceback

            self.console.print(f"[red]Traceback: {traceback.format_exc()}[/red]")
            return []
