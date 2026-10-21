## ADDED Requirements

### Requirement: Low stock
The shelf SHALL list the items whose quantity is at or below a given limit, in shelf order.

#### Scenario: Items at or below the limit
- **GIVEN** a shelf holding "bolt" 3, "nut" 10 and "washer" 5
- **WHEN** low stock is asked with limit 5
- **THEN** it lists "bolt" and "washer", in that order

#### Scenario: Nothing low
- **GIVEN** a shelf holding "nut" 10
- **WHEN** low stock is asked with limit 5
- **THEN** the list is empty
