# Actor Grid UI Documentation

## Overview

The Actor Grid UI is a compact, information-dense visualization for the actors and ships in SpaceSim2. It replaces the traditional vertical lists with a unified grid of entities, allowing for better screen space utilization and at-a-glance status monitoring of all entities on a planet.

## Key Components

### 1. Grid Layout
- Entities are represented as shapes arranged in a grid
- Multiple entities can be viewed simultaneously without scrolling
- Grid adapts to the available panel width
- Regular actors are rendered as squares
- Market makers are rendered as diamonds (rotated squares)
- Ships are rendered as circles

### 2. Detail Panel
- Bottom 60% of the left panel
- Shows detailed information about the hovered or selected entity
- Dynamically displays only relevant, non-zero information
- Groups information by category (basic stats, skills, inventory/cargo, actions)

## Visual Encoding

Entities are displayed with distinct shapes and colors to convey information at a glance:

### Shape
- Regular actors: Squares
- Market makers: Diamonds (rotated squares)
- Ships: Circles

### Base Color
- Regular actors: Gray/white (default)
- Market makers: Gold color
- Ships: Blue (default), Purple (in transit), Red (needs maintenance)
- Colors can change based on context (market view, process view)

### Selection and Hover State
- Selected entity: Highlighted with a bright border
- Hovered entity: Subtle gray border highlight
- Selected/hovered entity's details appear in the detail panel

## Context Awareness

The grid view adapts based on the current simulation context:

- **Default View**: Shows standard entity status
- **Market View**: Entity colors reflect market participation for the selected commodity
  - Market makers: Always shown in purple (diamond shape)
  - Regular actors/ships with both buy and sell orders: Purple-gold blend
  - Entities with buy orders: Green
  - Entities with sell orders: Red
  - Entities without orders: Darker version of default color
  - Quantities: When a commodity is selected, displays the inventory/cargo quantity owned by each entity (if non-zero)

Future context modes could include:
- Process view (colors based on skill proficiency)
- Resource view (colors based on inventory contents)
- Needs view (colors based on need satisfaction)

## Interaction

### Mouse Interaction
- **Hover**: Shows entity details without changing selection
- **Click**: Selects the entity and shows details
- **Click Selected Entity**: Deselects

### Keyboard Navigation
- **Arrow Keys**: Navigate the grid
- **Tab**: Switch between UI panels
- **Enter**: Select entity or interact with it

## Technical Implementation

### Core Classes
- `ActorListPanel`: Main UI component for the entity grid
- `InputHandler`: Processes mouse motion for hover effects

### Grid Calculation
- Grid dimensions are dynamically calculated based on panel width
- Entity squares/circles have configurable size (default 45px)
- Padding between entities is adjustable

### Rendering Process
1. Determine visible rows based on available space
2. Calculate entity index for each grid position
3. Render entity shapes with status indicators
4. Render detail panel for hovered/selected entity

## Detail Panel Information

The detail panel displays different information based on entity type:

### For Actors:
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

### For Ships:
1. **Basic Information**
   - Ship name and status
   - Current location or travel progress
   - Money

2. **Cargo Information**
   - Cargo capacity usage
   - Fuel level (if applicable)

3. **Cargo Contents** (non-zero items only)
   - Two-column layout for space efficiency

4. **Recent Actions**
   - Last ship action (traveling, trading, etc.)
   - Last market action (if applicable)

## Performance Considerations

- Only visible rows are rendered
- Detail display skips zero-value items
- Mouse motion handling is optimized to check only relevant areas
- Grid entities use simple shapes and minimal text
- Combined display reduces UI overhead compared to separate lists

## Implementation Benefits

Integrating ships with actors in a single grid provides several advantages:

1. **Unified Interface**: Users don't need to switch between separate modes to see different entity types
2. **Contextual Awareness**: Ships and actors can be viewed together in relation to markets
3. **Spatial Efficiency**: All entities can be seen at once without mode switching
4. **Consistent Interaction**: Uniform selection and navigation paradigm for all entity types
5. **Simplified Codebase**: Reduced duplicate code and consistent handling of entity interactions

## Future Enhancements

Potential future improvements include:
- Filterable entity grid (by type, activity, etc.)
- Sortable entities (by wealth, cargo value, etc.)
- Customizable display options
- Right-click context menu for entity actions
- Multi-select capabilities for batch operations
- Toggle to show/hide specific entity types
- Grouping by entity characteristics