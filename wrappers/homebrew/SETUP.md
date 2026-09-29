# Homebrew Tap Repository Structure

This directory contains the Homebrew tap for Argus SDK.

## Repository Layout

```
homebrew-argus/
├── Formula/
│   └── argus-sdk.rb      # Homebrew formula
└── README.md             # Tap documentation
```

## Setup Instructions

1. Create the GitHub repository:
   ```bash
   gh repo create Esthien-Labs/homebrew-argus --public --description "Homebrew tap for Argus SDK"
   ```

2. Push the tap:
   ```bash
   cd wrappers/homebrew
   git init
   git add .
   git commit -m "Initial Homebrew tap for Argus SDK"
   git remote add origin https://github.com/Esthien-Labs/homebrew-argus.git
   git push -u origin main
   ```

3. Update the formula SHA256 hashes after the first release:
   - Download the .pkg files from the GitHub release
   - Compute SHA256: `shasum -a 256 argus-sdk-0.7.4-macos-x64.pkg`
   - Update the formula with the correct hashes

## User Installation

Users can then install Argus SDK via:

```bash
brew tap esthien/argus
brew install argus-sdk
```

Or directly:

```bash
brew install esthien/argus/argus-sdk
```
