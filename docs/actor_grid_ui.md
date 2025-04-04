# Actor Grid UI Documentation

## Overview

The Actor Grid UI is a compact, information-dense visualization for the actors in SpaceSim2. It replaces the traditional vertical list with a grid of actor squares, allowing for better screen space utilization and at-a-glance status monitoring of large actor populations. 

## Key Components

### 1. Grid Layout
- Actors are represented as shapes arranged in a grid
- Multiple actors can be viewed simultaneously without scrolling
- Grid adapts to the available panel width
- Actors are rendered as squares (regular actors) or diamonds (market makers)

### 2. Detail Panel
- Bottom 60% of the left panel
- Shows detailed information about the hovered or selected actor
- Dynamically displays only relevant, non-zero information
- Groups information by category (basic stats, skills, inventory, actions)

## Visual Encoding

Actors are displayed with distinct shapes and colors to convey information at a glance:

### Shape
- Regular actors: Squares
- Market makers: Diamonds (rotated squares)

### Base Color
- Regular actors: Gray/white (default)
- Market makers: Gold color
- Colors can change based on context (market view, process view)

### Selection and Hover State
- Selected actor: Highlighted with a bright border
- Hovered actor: Subtle gray border highlight
- Selected/hovered actor's details appear in the detail panel

## Context Awareness

The grid view adapts based on the current simulation context:

- **Default View**: Shows standard actor status
- **Market View**: Actor colors reflect market participation for the selected commodity
  - Market makers: Always shown in purple (diamond shape)
  - Regular actors with both buy and sell orders: Purple-gold blend
  - Regular actors with buy orders: Green
  - Regular actors with sell orders: Red
  - Regular actors without orders: Darker version of default color
  - Quantities: When a commodity is selected, displays the inventory quantity owned by each actor (if non-zero)

Future context modes could include:
- Process view (colors based on skill proficiency)
- Resource view (colors based on inventory contents)
- Needs view (colors based on need satisfaction)

## Interaction

### Mouse Interaction
- **Hover**: Shows actor details without changing selection
- **Click**: Selects the actor and shows details
- **Click Selected Actor**: Deselects

### Keyboard Navigation
- **Arrow Keys**: Navigate the grid
- **Tab**: Switch between UI panels
- **S Key**: Toggle between actors and ships view

## Technical Implementation

### Core Classes
- `ActorListPanel`: Main UI component for the actor grid
- `InputHandler`: Processes mouse motion for hover effects

### Grid Calculation
- Grid dimensions are dynamically calculated based on panel width
- Actor squares have configurable size (default 45px)
- Padding between squares is adjustable

### Rendering Process
1. Determine visible rows based on available space
2. Calculate actor index for each grid position
3. Render actor squares with status indicators
4. Render detail panel for hovered/selected actor

## Detail Panel Information

The detail panel displays:

1. **Basic Information**
   - Actor name and type
   - Current money
   - Food status (if non-zero)

2. **Notable Skills Section**
   - Only displays skills that significantly deviate from baseline (1.0)
   - Shows skills with >20% increase or >20% decrease from baseline
   - Uses percentage format (e.g., "+25%" or "-30%")
   - Color coded: green for above-average skills, orange for below-average skills

3. **Inventory Section** (non-zero items only)
   - Two-column layout for space efficiency
   - Available and reserved quantities when applicable

4. **Recent Actions**
   - Last economic action
   - Last market action (truncated if too long)

## Performance Considerations

- Only visible rows are rendered
- Detail display skips zero-value items
- Mouse motion handling is optimized to check only relevant areas
- Grid squares use simple shapes and minimal text

## Future Enhancements

Potential future improvements include:
- Filterable actor grid (by type, activity, etc.)
- Sortable actors (by wealth, skill, etc.)
- Customizable display options
- Right-click context menu for actor actions
- Multi-select capabilities for batch operations