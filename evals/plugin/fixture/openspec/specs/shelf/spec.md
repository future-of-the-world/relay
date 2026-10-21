# shelf Specification

## Purpose
A shelf is a list of stock items. It adds items, counts them and reads a saved copy.

## Requirements

### Requirement: Adding items
The shelf SHALL add an item by name and quantity; adding a name that is already on the shelf SHALL increase its quantity.

#### Scenario: New item
- **GIVEN** an empty shelf
- **WHEN** "bolt" is added with quantity 3
- **THEN** the shelf holds "bolt" with quantity 3

#### Scenario: Existing item
- **GIVEN** a shelf holding "bolt" with quantity 3
- **WHEN** "bolt" is added with quantity 2
- **THEN** the shelf holds "bolt" with quantity 5

#### Scenario: Quantity not positive
- **WHEN** an item is added with quantity 0 or less
- **THEN** the shelf rejects it and stays unchanged

### Requirement: Total
The shelf SHALL report the total quantity of all items.

#### Scenario: Sum
- **GIVEN** a shelf holding "bolt" 3 and "nut" 4
- **WHEN** the total is asked
- **THEN** it is 7
