<img width="3188" height="1202" alt="frame (3)" src="https://github.com/user-attachments/assets/517ad8e9-ad22-457d-9538-a9e62d137cd7" />


# [S7] 🎯


## Basic Details
### Team Name: [TEAM MAX]


### Team Members
- Member 1: [JOHN THOMAS P] - [CUCEK]
- Member 2: [NAVEEN V.B] - [CUCEK]

### Project Description
try this link
https://super7.onrender.com/app ...
Cricket Card Game built with Python Django, where players compete against the computer in a 7-round match using cricket-themed cards. Each round compares batting and bowling stats to determine runs or wickets, starting with a toss to decide the innings.

### The Problem (that doesn't exist)
We're bringing back the nostalgic fun of childhood cricket card games by creating an online version, so even if everyone’s too busy or far apart, they can still enjoy a quick match anytime, anywhere.

### The Solution (that nobody asked for)
By turning those old-school cricket cards into a fast-paced, 7-round digital showdown! With a toss to start, strategic card picks, and thrilling run vs. wicket battles against the computer — it’s like street cricket meets card strategy, now just a click away!

## Technical Details
### Technologies/Components Used
For Software:
Languages used: Python, JavaScript, HTML
Frameworks used: Django (Python)
Libraries used: CSV (for data handling), Pillow (for image processing)
Tools used: Python, CSV files, Pillow


### Implementation
For Software:
This project is developed using Python Django as the backend framework to power the core logic of the game.

Key Features & Architecture:
Game Flow:
Begins with a toss (user selects heads or tails).
Followed by 7 rounds of turn-based card play between player and computer.
Each round compares batting vs. bowling points to determine runs or wickets.
After the first innings, the other side bats and tries to chase the score.

Database (SQLite):
Stores user data, game results, match statistics, and player performance.

CSV Files:
Used to log past game history, helping users analyze previous matchups.
Enables the possibility of strategic decision-making by reviewing outcomes and optimizing card choices.

Tools & Libraries:
Pillow: For managing and rendering player card images.
CSV module: For reading/writing gameplay logs.
Django ORM: For managing database interactions.
This implementation recreates the charm of cricket card games with added intelligence and persistence, offering both fun and strategy!
# Installation
pip install -r requirements.txt


# Run
Open a terminal or command prompt and navigate to your project folder where manage.py is located. Then run:
python manage.py runserver
Access the app in your browser:

Open your browser and go to:
http://127.0.0.1:8000/

### Project Documentation
For Software:

# Screenshots (Add at least 3)
https://drive.google.com/drive/folders/1EQQtL0Iy5REmTAps9RvFwnjaM3HpraMJ
game mode:you can select players from the deck

https://drive.google.com/drive/folders/1EPvIrZDddYlyZULYCRR-fCaP3D8qznxV
toss result

https://drive.google.com/drive/folders/1EDZjsERtz-YCvdghFXBDyU49Nygakvz8
playing deck

https://drive.google.com/drive/folders/1EI2nDc6W1LavL54t2vitnvhAQHSXlaLO
match making ,choose head or tail

# Diagrams
![Workflow](Add your workflow/architecture diagram here)
*Add caption explaining your workflow*



### Project Demo
# Video
(https://drive.google.com/drive/folders/1DNMzwwS4JOBdc5HUq-uUQ65wkmYbY-o3)


### 1. **Toss Phase**
- **Start**: The game begins at `https://super7.onrender.com` (or locally at `http://127.0.0.1:8000/`) with an animated S7 logo preloader, followed by the `toss.html` page.
- **Action**: The player selects "head" or "tails" and submits the form.
- **Logic**: In `toss_view`, a random outcome ("head" or "tails") is generated. If the player’s choice matches, they win; otherwise, the computer randomly decides who bats first (`player` or `computer`).
- **Outcome**: The `toss_result.html` page displays the result. If the player wins, they choose to bat or field via a form; if they lose, the computer’s choice is shown, and the game proceeds.

### 2. **Game Start and First Innings**
- **Transition**: From `toss_result.html`, a form submission or link directs to `game_start` with the `batting_first` decision stored in the session.
- **Setup**: `game_start` initializes the game state (scores, wickets, used cards) in the session for 7 rounds per innings.
- **Gameplay**: The player selects a card from available `PlayerCard` objects. The AI counters with a card based on a strategy from `strategies.csv` (e.g., high bowling vs. high batting).
- **Round Logic**: If the player’s card batting > computer’s bowling, runs are added; otherwise, a wicket falls. Results are saved to `game_history.csv`.
- **Progress**: After 7 rounds, the first innings ends, setting a target (`first_score + 1`).

### 3. **Second Innings**
- **Start**: The second innings begins with the other team batting, aiming to exceed the target.
- **Gameplay**: Similar to the first innings, with 7 rounds unless 10 wickets are lost. The AI adapts strategies using `game_history.csv` analysis.
- **End Condition**: If `second_score > first_score` after 7 rounds or all wickets fall, the game ends.

### 4. **Game Over**
- **Result**: `game_start` determines the winner (higher score, tie if equal) and renders `game_result.html` with final scores and wickets.
- **Display**: The page shows the winning team or a tie, concluding the game.

### Summary
The flow is: Toss → First Innings (7 rounds) → Second Innings (7 rounds or all out) → Game Over, driven by Django views, session management, and CSV-based AI logic, with history enhancing strategy over time.



---
Made with ❤️ at TinkerHub Useless Projects 

![Static Badge](https://img.shields.io/badge/TinkerHub-24?color=%23000000&link=https%3A%2F%2Fwww.tinkerhub.org%2F)
![Static Badge](https://img.shields.io/badge/UselessProjects--25-25?link=https%3A%2F%2Fwww.tinkerhub.org%2Fevents%2FQ2Q1TQKX6Q%2FUseless%2520Projects)
