
import os
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass, field
from pathlib import Path

from .i18n_manager import I18NManager
from .translation_group import TranslationGroup
from .translation_manager_results import TranslationAction
from utils.logging_setup import get_logger
from utils.settings_manager import SettingsManager

logger = get_logger("cross_project_analyzer")

@dataclass
class TranslationMatch:
    """Represents a translation match found across projects."""
    source_project: str
    source_msgid: str
    source_translation: str
    target_project: str
    target_msgid: str
    target_locale: str
    confidence: float = 1.0  # 1.0 for exact matches, lower for fuzzy matches
    
    def __str__(self):
        return f"Match: '{self.source_msgid}' ({self.source_translation}) -> '{self.target_msgid}' ({self.target_locale}) from {self.source_project}"

@dataclass
class MsgIdMatchGroup:
    """Represents a group of translation matches for a single msgid."""
    source_project: str
    target_msgid: str
    filled_locales_count: int = 0
    fillable_locales_count: int = 0
    unfillable_locales_count: int = 0
    total_target_locales: int = 0
    matches: List[TranslationMatch] = field(default_factory=list)
    
    @property
    def total_matches(self) -> int:
        """Total number of matches for this msgid."""
        return len(self.matches)
    
    @property
    def match_rate(self) -> float:
        """Calculate match rate as percentage of target locales that can be filled."""
        if self.total_target_locales == 0:
            return 0.0
        return ((self.filled_locales_count + self.fillable_locales_count) / self.total_target_locales) * 100

@dataclass
class CrossProjectAnalysis:
    """Results of cross-project translation analysis."""
    source_project: str
    target_project: str
    matches_found: List[TranslationMatch] = field(default_factory=list)
    missing_matches: List[TranslationMatch] = field(default_factory=list)  # Matches for actually missing translations
    selected_matches: List[TranslationMatch] = field(default_factory=list)  # Matches for selected translations
    msgid_groups: List[MsgIdMatchGroup] = field(default_factory=list)  # Grouped by msgid for display
    total_analyzed: int = 0
    total_matched: int = 0
    analysis_timestamp: Optional[str] = None
    
    @property
    def match_rate(self) -> float:
        """Calculate the match rate as a percentage."""
        if self.total_analyzed == 0:
            return 0.0
        return (self.total_matched / self.total_analyzed) * 100

class CrossProjectAnalyzer:
    """Analyzes translations across multiple projects to find matches and suggest pre-fills."""
    
    def __init__(self, settings_manager: SettingsManager):
        self.settings_manager = settings_manager
        self._project_managers: Dict[str, I18NManager] = {}
        
    def get_available_projects(self) -> List[str]:
        """Get list of available projects from recent projects.
        
        Returns:
            List[str]: List of valid project paths
        """
        projects = self.settings_manager.load_recent_projects()
        logger.debug(f"Settings manager returned projects: {projects}")
        return projects
    
    def _get_project_default_locale(self, project_path: str) -> Optional[str]:
        """Get the default locale for a project without creating a full manager.
        
        Args:
            project_path (str): Path to the project
            
        Returns:
            Optional[str]: Default locale if project is valid, None otherwise
        """
        try:
            # Check if project has required structure
            locale_dir = os.path.join(project_path, "locale")
            if not os.path.exists(locale_dir):
                return None
                
            # Try to get project-specific default locale first
            project_default = self.settings_manager.get_project_default_locale(project_path)
            if project_default:
                logger.debug(f"Using project-specific default locale for {project_path}: {project_default}")
                return project_default
                
            # Fall back to creating a minimal manager to get the default locale
            manager = I18NManager(project_path, intro_details=self.settings_manager.get_intro_details(), settings_manager=self.settings_manager)
            return manager.default_locale
            
        except Exception as e:
            logger.debug(f"Error getting default locale for project {project_path}: {e}")
            return None

    def _get_or_create_manager(self, project_path: str) -> Optional[I18NManager]:
        """Get or create an I18NManager for a project.
        
        Args:
            project_path (str): Path to the project
            
        Returns:
            Optional[I18NManager]: Manager instance or None if project is invalid
        """
        if project_path in self._project_managers:
            logger.debug(f"Using cached manager for project: {project_path}")
            return self._project_managers[project_path]
            
        logger.debug(f"Creating new manager for project: {project_path}")
        
        try:
            # Create manager and load translations
            manager = I18NManager(project_path, intro_details=self.settings_manager.get_intro_details(), settings_manager=self.settings_manager)
            
            # Run status check to load translations
            logger.debug(f"Running status check for project: {project_path}")
            results = manager.manage_translations()
            if not results.action_successful:
                logger.warning(f"Failed to load translations for project {project_path}: {results.error_message}")
                return None
                
            logger.debug(f"Successfully loaded project {project_path}: {len(manager.translations)} translations, {len(manager.locales)} locales")
            self._project_managers[project_path] = manager
            return manager
            
        except Exception as e:
            logger.error(f"Error creating manager for project {project_path}: {e}")
            return None
    
    def analyze_project_pair(self, source_project: str, target_project: str, 
                           target_locales: Optional[List[str]] = None) -> CrossProjectAnalysis:
        """Analyze translations between two projects to find matches.
        
        Args:
            source_project (str): Path to the source project (to find translations from)
            target_project (str): Path to the target project (to find missing translations in)
            target_locales (Optional[List[str]]): Specific locales to analyze in target project
            
        Returns:
            CrossProjectAnalysis: Analysis results with found matches
        """
        logger.info(f"Analyzing translation matches from {source_project} to {target_project}")
        
        
        # Check default locale compatibility first (before creating managers)
        source_default = self._get_project_default_locale(source_project)
        target_default = self._get_project_default_locale(target_project)
        
        if not source_default or not target_default:
            logger.debug(f"Could not determine default locale - source: {source_default}, target: {target_default}")
            return CrossProjectAnalysis(source_project, target_project)
        
        if source_default != target_default:
            logger.debug(f"Skipping incompatible projects - source default: {source_default}, target default: {target_default}")
            return CrossProjectAnalysis(source_project, target_project)
        
        logger.debug(f"Projects compatible - both use default locale: {source_default}")
        
        # Now create managers for compatible projects
        source_manager = self._get_or_create_manager(source_project)
        target_manager = self._get_or_create_manager(target_project)
        
        if not source_manager or not target_manager:
            logger.warning(f"Could not create managers - source: {source_manager is not None}, target: {target_manager is not None}")
            return CrossProjectAnalysis(source_project, target_project)
        
        logger.debug(f"Source project: {len(source_manager.translations)} translations, {len(source_manager.locales)} locales")
        logger.debug(f"Target project: {len(target_manager.translations)} translations, {len(target_manager.locales)} locales")
        
        # Determine target locales to analyze
        if target_locales is None:
            target_locales = list(target_manager.locales)
        
        logger.debug(f"Analyzing {len(target_locales)} target locales")
        
        analysis = CrossProjectAnalysis(source_project, target_project)
        analysis.total_analyzed = len(target_manager.translations)
        logger.debug(f"Target project has {len(target_manager.translations)} translations to analyze")
        
        # Find matches for ALL translation groups (not just missing ones) for user confidence
        all_matches = []
        missing_matches = []
        msgid_groups = {}  # Group matches by msgid
        
        for msgid, target_group in target_manager.translations.items():
            if not target_group.is_in_base:
                continue  # Skip stale translations
                
            # Initialize group for this msgid
            if msgid not in msgid_groups:
                msgid_groups[msgid] = MsgIdMatchGroup(
                    source_project=source_project,
                    target_msgid=msgid,
                    total_target_locales=len(target_locales)
                )
            
            group = msgid_groups[msgid]
            filled_count = 0
            fillable_count = 0
            unfillable_count = 0
            
            # First, count all filled translations in target (regardless of source matches)
            for locale in target_locales:
                target_translation = target_group.get_translation(locale)
                if target_translation and target_translation.strip():
                    filled_count += 1
            
            # Now check each target locale for matches
            for locale in target_locales:
                # logger.debug(f"Looking for match for msgid '{msgid}' in locale '{locale}'")
                
                # Look for exact match in source project
                match = self._find_exact_match(
                    source_manager, target_manager, 
                    msgid, locale, source_default
                )
                
                # Check current target translation status
                target_translation = target_group.get_translation(locale)
                is_filled = target_translation and target_translation.strip()
                
                if match:
                    # logger.debug(f"Found match: {match}")
                    all_matches.append(match)
                    group.matches.append(match)
                    
                    # If target is not filled, this is fillable
                    if not is_filled:
                        fillable_count += 1
                        # logger.debug(f"Translation is missing - adding to missing_matches")
                        missing_matches.append(match)
                        analysis.total_matched += 1
                    # else:
                        # logger.debug(f"Translation already exists - not adding to missing_matches")
                else:
                    # No match found for this locale
                    if not is_filled:
                        unfillable_count += 1
                        # logger.debug(f"No match found for unfilled locale '{locale}'")
            
            # Update group counts
            group.filled_locales_count = filled_count
            group.fillable_locales_count = fillable_count
            group.unfillable_locales_count = unfillable_count
        
        # Store all matches for display, but track which ones are actually missing
        analysis.matches_found = all_matches
        analysis.missing_matches = missing_matches  # New field for actual missing translations
        
        # Filter out groups with no fillable translations
        filtered_groups = [group for group in msgid_groups.values() if group.fillable_locales_count > 0]
        analysis.msgid_groups = filtered_groups
        
        logger.info(f"Found {len(all_matches)} total matches, {len(missing_matches)} missing translations out of {analysis.total_analyzed} analyzed")
        logger.info(f"Created {len(filtered_groups)} msgid groups with fillable translations (filtered from {len(msgid_groups)} total groups)")
        return analysis
    
    def _find_exact_match(self, source_manager: I18NManager, target_manager: I18NManager,
                         target_msgid: str, target_locale: str, default_locale: str) -> Optional[TranslationMatch]:
        """Find an exact translation match in the source project.
        
        Args:
            source_manager (I18NManager): Manager for source project
            target_manager (I18NManager): Manager for target project
            target_msgid (str): The msgid to find a translation for
            target_locale (str): The locale needing translation
            default_locale (str): The default locale (usually 'en')
            
        Returns:
            Optional[TranslationMatch]: Match if found, None otherwise
        """
        # logger.debug(f"Finding match for msgid '{target_msgid}' in locale '{target_locale}'")
        
        # Strategy 1: Look for exact msgid match in source project
        if target_msgid in source_manager.translations:
            # logger.debug(f"Found exact msgid match in source project")
            source_group = source_manager.translations[target_msgid]
            
            # Check if source has translation for target locale
            if target_locale in source_group.values:
                source_translation = source_group.values[target_locale]
                # logger.debug(f"Source has target locale '{target_locale}': '{source_translation}' (strip: '{source_translation.strip()}')")
                if source_translation.strip():
                    # logger.debug(f"Found translation for target locale '{target_locale}': '{source_translation}'")
                    return TranslationMatch(
                        source_project=source_manager._directory,
                        source_msgid=target_msgid,
                        source_translation=source_translation,
                        target_project=target_manager._directory,
                        target_msgid=target_msgid,
                        target_locale=target_locale
                    )
            #     else:
            #         logger.debug(f"Target locale translation is empty or whitespace")
            # else:
            #     logger.debug(f"Source does not have target locale '{target_locale}'")
        #         else:
        #             logger.debug(f"Default locale translation is empty or whitespace")
        #     else:
        #         logger.debug(f"Source does not have default locale '{default_locale}'")
        # else:
        #     logger.debug(f"No exact msgid match found in source project")
        
        # Strategy 2: Look for exact default locale translation match
        # This handles cases where the msgid is different but the English text is the same
        target_default_translation = target_manager.translations[target_msgid].get_translation(default_locale)
        if target_default_translation and target_default_translation.strip():
            # logger.debug(f"Looking for default locale match: '{target_default_translation}'")
            match_count = 0
            for source_msgid, source_group in source_manager.translations.items():
                source_default = source_group.get_translation(default_locale)
                if (source_default and source_default.strip() and 
                    source_default == target_default_translation):
                    
                    match_count += 1
                    # logger.debug(f"Found matching default translation in source msgid '{source_msgid}' (match #{match_count})")
                    # Check if source has translation for target locale
                    if target_locale in source_group.values:
                        source_translation = source_group.values[target_locale]
                        # logger.debug(f"Source has target locale '{target_locale}': '{source_translation}' (strip: '{target_translation.strip()}')")
                        if source_translation.strip():
                            # logger.debug(f"Found translation for target locale '{target_locale}': '{source_translation}'")
                            return TranslationMatch(
                                source_project=source_manager._directory,
                                source_msgid=source_msgid,
                                source_translation=source_translation,
                                target_project=target_manager._directory,
                                target_msgid=target_msgid,
                                target_locale=target_locale
                            )
                    #     else:
                    #         logger.debug(f"Target locale translation is empty or whitespace")
                    # else:
                    #     logger.debug(f"Source does not have target locale '{target_locale}'")
            
            # if match_count == 0:
            #     logger.debug(f"No matching default translations found")
            # else:
            #     logger.debug(f"Found {match_count} matching default translations but none had target locale '{target_locale}'")
        # else:
        #     logger.debug(f"No default locale translation available for target msgid")
        
        # logger.debug(f"No match found for msgid '{target_msgid}' in locale '{target_locale}'")
        return None
    
    def apply_matches_to_target(self,
                                analysis: CrossProjectAnalysis,
                                apply_all_matches: bool = False, 
                                apply_selected_matches: bool = False,
                                dry_run: bool = True) -> Dict[str, int]:
        """Apply found translation matches to the target project.
        
        Args:
            analysis (CrossProjectAnalysis): Analysis results with matches to apply
            apply_all_matches (bool): If True, apply all matches (including filled translations), 
                                    if False, only apply missing translations
            apply_selected_matches (bool): If True, apply selected matches, if False, apply all matches
            dry_run (bool): If True, only show what would be applied without making changes
            
        Returns:
            Dict[str, int]: Summary of applied changes by locale
        """
        # Choose which matches to apply
        if apply_selected_matches:
            matches_to_apply = analysis.selected_matches
        else:
            matches_to_apply = analysis.matches_found if apply_all_matches else analysis.missing_matches
        logger.debug(f"Applying {len(matches_to_apply)} matches to target project {analysis.target_project}")
        
        if not matches_to_apply:
            if apply_all_matches:
                logger.info("No matches to apply")
            else:
                logger.info("No missing translations to apply")
            return {}
        
        target_manager = self._get_or_create_manager(analysis.target_project)
        if not target_manager:
            logger.error(f"Could not load target project manager for {analysis.target_project}")
            return {}
        
        applied_changes = {}
        
        for match in matches_to_apply:
            if match.target_msgid in target_manager.translations:
                target_group = target_manager.translations[match.target_msgid]
                
                # Check if translation is already filled (for missing matches only)
                if not apply_all_matches:
                    existing_translation = target_group.get_translation(match.target_locale)
                    if existing_translation and existing_translation.strip():
                        logger.debug(f"Skipping already filled translation: {match}")
                        continue
                
                if not dry_run:
                    # Apply the translation
                    target_group.add_translation(match.target_locale, match.source_translation)
                    logger.info(f"Applied translation: {match}")
                else:
                    logger.info(f"Would apply translation: {match}")
                
                # Track changes by locale
                if match.target_locale not in applied_changes:
                    applied_changes[match.target_locale] = 0
                applied_changes[match.target_locale] += 1
            else:
                logger.error(f"Could not find target msgid {match.target_msgid} in target project {target_manager._directory}")
        
        if not dry_run and applied_changes:
            # Write PO files for affected locales
            affected_locales = set(applied_changes.keys())
            results = target_manager.manage_translations(
                action=TranslationAction.WRITE_PO_FILES,
                modified_locales=affected_locales
            )
            
            if not results.action_successful:
                logger.error(f"Failed to write PO files after applying translations: {results.error_message}")
        
        return applied_changes
    
    def analyze_all_projects(self, target_project: str, 
                           target_locales: Optional[List[str]] = None) -> List[CrossProjectAnalysis]:
        """Analyze translations from all available projects to the target project.
        
        Args:
            target_project (str): Path to the target project
            target_locales (Optional[List[str]]): Specific locales to analyze
            
        Returns:
            List[CrossProjectAnalysis]: List of analysis results for each source project
        """
        logger.debug(f"=== Starting analyze_all_projects ===")
        logger.debug(f"Target project: {target_project}")
        logger.debug(f"Target project basename: {os.path.basename(target_project)}")
        logger.debug(f"Target locales: {target_locales}")
        
        # Ensure target project has a POT file by generating it if needed
        # This is done once at the highest level to avoid regenerating for each project pair
        target_manager = self._get_or_create_manager(target_project)
        if not target_manager:
            logger.warning(f"Could not create manager for target project {target_project}")
            return []  # Return empty list if manager creation fails
            
        # Generate POT file for the target project
        if not target_manager.generate_pot_file():
            logger.warning(f"Failed to generate POT file for target project {target_project}")
            return []  # Return empty list if POT generation fails
        
        available_projects = self.get_available_projects()
        logger.debug(f"Available projects: {available_projects}")
        logger.debug(f"Number of available projects: {len(available_projects)}")
        
        analyses = []
        
        for source_project in available_projects:
            logger.debug(f"Checking source project: {source_project}")
            logger.debug(f"Source project basename: {os.path.basename(source_project)}")
            if source_project == target_project:
                logger.debug(f"Skipping self-analysis for {source_project}")
                continue  # Skip self-analysis
                
            logger.debug(f"Analyzing source project: {source_project}")
            analysis = self.analyze_project_pair(source_project, target_project, target_locales)
            logger.debug(f"Analysis result: {len(analysis.matches_found)} matches found, {len(analysis.missing_matches)} missing")
            if analysis.matches_found:
                analyses.append(analysis)
            else:
                logger.debug(f"No matches found for source project: {source_project}")
        
        logger.debug(f"Total analyses with matches: {len(analyses)}")
        
        # Sort by match rate (highest first)
        analyses.sort(key=lambda x: x.match_rate, reverse=True)
        return analyses
    
    def get_consolidated_matches(self, analyses: List[CrossProjectAnalysis]) -> List[TranslationMatch]:
        """Consolidate matches from multiple analyses, removing duplicates.
        
        Args:
            analyses (List[CrossProjectAnalysis]): List of analyses to consolidate
            
        Returns:
            List[TranslationMatch]: Consolidated list of unique matches
        """
        consolidated = {}
        
        for analysis in analyses:
            for match in analysis.matches_found:
                # Create a unique key for each target msgid + locale combination
                key = (match.target_msgid, match.target_locale)
                
                # Keep the match with highest confidence (or first one if equal)
                if key not in consolidated or match.confidence > consolidated[key].confidence:
                    consolidated[key] = match
        
        return list(consolidated.values())
    
    def clear_cache(self):
        """Clear the cached project managers."""
        self._project_managers.clear()
        logger.debug("Cleared project manager cache") 