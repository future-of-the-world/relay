## ADDED Requirements

### Requirement: Saved shelf
The shelf SHALL be saved to a JSON file and SHALL be read back from that file on the next run.

#### Scenario: Save and read back
- **GIVEN** a shelf holding "bolt" 3
- **WHEN** the shelf is saved to a file and read back
- **THEN** it holds "bolt" 3

#### Scenario: First run
- **WHEN** the shelf is read back and no file exists yet
- **THEN** the shelf is empty

#### Scenario: Corrupt data
- **GIVEN** a shelf file that is not valid JSON
- **WHEN** the shelf is read back
- **THEN** the shelf is empty and the file is left as it is

#### Scenario: Older data
- **GIVEN** a shelf file saved by an older version, whose items have no `qty` field
- **WHEN** the shelf is read back
- **THEN** each item is read with qty 1

#### Scenario: Storage unavailable
- **GIVEN** storage that is unavailable, so the file cannot be read
- **WHEN** the shelf is read back
- **THEN** the shelf is empty and the person is told the file could not be read
