# 🔬 PLAGENOR 4.0

**Plateforme de Gestion des Demandes d'Analyses Génomiques**
ESSBO — École Supérieure des Sciences Biologiques d'Oran

---

## Quick Start

```bash
# 1. Enter project directory
cd plagenor

# 2. Create virtual environment
python -m venv .venv
source .venv/bin/activate        # Linux / Mac / WSL
# .venv\Scripts\activate         # Windows CMD

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env

# 5. Launch
bash run.sh
# or on Windows: run.bat
