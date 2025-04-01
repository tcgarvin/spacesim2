from typing import Dict, List, Optional, Set
import random
import yaml


class Skill:
    """Represents a skill that actors can possess at different levels."""
    
    def __init__(self, id: str, name: str, description: str):
        """Initialize a skill definition.
        
        Args:
            id: Unique identifier for the skill
            name: Human-readable name
            description: Description of what the skill represents
        """
        self.id = id
        self.name = name
        self.description = description
    
    def __str__(self) -> str:
        return self.name


class SkillsRegistry:
    """Registry for skills in the simulation."""
    
    def __init__(self):
        """Initialize an empty skills registry."""
        self._skills: Dict[str, Skill] = {}
    
    def register_skill(self, skill: Skill) -> None:
        """Register a skill in the registry.
        
        Args:
            skill: The skill to register
        """
        self._skills[skill.id] = skill
    
    def get_skill(self, skill_id: str) -> Optional[Skill]:
        """Get a skill by its ID.
        
        Args:
            skill_id: The ID of the skill to retrieve
            
        Returns:
            The skill if found, None otherwise
        """
        return self._skills.get(skill_id)
    
    def all_skills(self) -> List[Skill]:
        """Get all registered skills.
        
        Returns:
            List of all skills
        """
        return list(self._skills.values())
    
    def load_from_file(self, filepath: str) -> None:
        """Load skills from a YAML file.
        
        Args:
            filepath: Path to the YAML file
        """
        try:
            with open(filepath, 'r') as f:
                skills_data = yaml.safe_load(f)
                
            for skill_data in skills_data:
                skill = Skill(
                    id=skill_data['id'],
                    name=skill_data['name'],
                    description=skill_data['description']
                )
                self.register_skill(skill)
        except Exception as e:
            print(f"Error loading skills from {filepath}: {e}")


class SkillCheck:
    """Utility class for performing skill checks."""
    
    @staticmethod
    def success_check(skill_rating: float) -> bool:
        """Determine if a skill check succeeds.
        
        Args:
            skill_rating: The actor's skill rating
            
        Returns:
            True if the check succeeds, False otherwise
        """
        # Skill rating ≥ 1.0: 100% success
        if skill_rating >= 1.0:
            return True
        
        # Skill rating < 1.0: Success probability proportional to rating
        # (e.g., 0.8 rating → 80% success chance)
        return random.random() < skill_rating
    
    @staticmethod
    def multiplier_check(skill_rating: float) -> bool:
        """Determine if a skill check results in a multiplier.
        
        Args:
            skill_rating: The actor's skill rating
            
        Returns:
            True if a multiplier should be applied, False otherwise
        """
        # Skill rating <= 1.0: No multiplier
        if skill_rating <= 1.0:
            return False
        
        # Multiplier chance = (Skill Rating - 1.0) × 50%
        multiplier_chance = (skill_rating - 1.0) * 0.5
        return random.random() < multiplier_chance
    
    @staticmethod
    def get_combined_skill_rating(skill_ratings: List[float]) -> float:
        """Calculate the combined rating for multiple skills.
        
        Args:
            skill_ratings: List of individual skill ratings
            
        Returns:
            The average of all skill ratings
        """
        if not skill_ratings:
            return 0.5  # Default to unskilled if no skills provided
        
        return sum(skill_ratings) / len(skill_ratings)