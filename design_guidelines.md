# Design Guidelines - eBay Seller Hub Style

## Theme: Light, Clean, Professional
**Core Principle**: White backgrounds, high contrast, minimal clicks. Similar to eBay Seller Hub's clean professional interface.

## Color Palette

### Base Colors
- **Page Background**: White (#ffffff)
- **Card Background**: White (#ffffff)
- **Text Primary**: Dark grey (#212529)
- **Text Secondary**: Medium grey (#6c757d)
- **Borders**: Light grey (#dee2e6)
- **Hover State**: Very light grey (#f8f9fa)

### Navigation
- **Top Bar**: Dark (#343a40) or brand color
- **Sub-navigation**: White with bottom border
- **Active Tab**: Primary blue accent

### Marketplace Badge Colors
- **eBay**: Blue (#0d6efd) with white text
- **Amazon FBM**: Orange (#fd7e14) with white text  
- **Amazon FBA**: Green (#198754) with white text
- **Shopify**: Purple (#6f42c1) with white text

### Status Colors
- **In Stock**: Green badge
- **Low Stock**: Yellow/amber badge
- **Out of Stock**: Red badge
- **Linked**: Green badge
- **Unlinked**: Yellow warning badge

## Typography

### Font Stack
```css
font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, 'Helvetica Neue', Arial, sans-serif;
```

### Hierarchy
- **Page Title**: 1.5rem (24px), semibold, #212529
- **Section Headers**: 1.25rem (20px), semibold
- **Table Headers**: 0.875rem (14px), uppercase, semibold, #6c757d
- **Body Text**: 1rem (16px), regular, #212529
- **KPI Numbers**: 2rem+ (32px+), bold
- **Small/Labels**: 0.875rem (14px)

### Rules
- No tiny fonts (minimum 12px)
- No long ALL CAPS text
- Dark text on light backgrounds only

## Navigation Structure

### Main Tabs (Top Bar)
```
Inventory | Orders | Listings | Analytics | Settings
```

### Inventory Sub-Navigation
```
[ Master Stock ] [ Product Linking ] [ Publish (greyed) ]
```

## Tables

### Style
- White background with light grey borders
- No dark cards or backgrounds for main content
- Clear hover state (light grey)
- Consistent padding (px-4 py-3)

### Standard Columns (Master Stock)
1. Image (thumbnail)
2. SKU (code style)
3. Product Name
4. Available (quantity)
5. Marketplaces (badges)
6. Status (In Stock / Low Stock / Reorder)
7. Actions (View/Edit, Product Linking, Diagnostics)

### Standard Columns (Product Linking - Warehouse)
1. Warehouse SKU
2. Product Name
3. Stock (available)
4. Linked Marketplaces (badges)
5. Actions (Link more, Diagnostics)

### Standard Columns (Product Linking - Unlinked)
1. Title
2. Listing SKU
3. Marketplace
4. Store
5. Stock
6. Actions (Link to Warehouse)

## KPI Cards

### Style
- Flat white cards with subtle shadow
- Large bold numbers (2rem+)
- Clear descriptive labels
- Optional small trend indicator

### Master Stock KPIs
1. Total SKUs
2. Low Stock
3. Total Units
4. Linked to Marketplaces

## Modals

### Structure
- White background
- Clear header with title
- Search box at top (for list modals)
- Scrollable content area
- Footer with action buttons

### Link More Modal
```
Title: "Link more listings to: <SKU> - <Product Name>"
Search: "Search unlinked listings by SKU, ASIN, eBay Item ID, or title..."
Table: Marketplace | Store | Listing SKU | Title | Stock | [Link]
```

### Link to Warehouse Modal
```
Header: Listing details (read-only box)
Search: "Search warehouse SKU or product name..."
Table: Warehouse SKU | Product Name | Stock | [Link]
```

## Buttons

### Hierarchy
- **Primary**: Solid blue (#0d6efd), white text
- **Secondary**: Outline blue or grey
- **Success**: Solid green (#198754)
- **Danger**: Solid red for destructive actions

### Sizes
- Default: Standard Bootstrap btn-sm or btn
- Groups: btn-group with icon buttons

## Responsive

### Mobile Adjustments
- Single column layouts
- Collapsible navigation
- Stacked table cells where needed
- Full-width buttons

## Do's and Don'ts

### Do
- Use white backgrounds for main content
- High contrast text (dark on light)
- Clear visual hierarchy
- Consistent spacing
- Flat, clean cards

### Don't
- Dark grey cards with low-contrast text
- Tiny fonts
- Long ALL CAPS text
- Complex multi-step wizards (prefer flat lists)
- Hidden or nested critical actions
