"""
PLAGENOR Service Pricing Engine
Implements official IBTIKAR-DGRSDT pricing rules extracted from DOCX service files.
All pricing logic is authoritative and matches official EGTP form versions.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.exceptions import PlagenorError


class PricingError(PlagenorError):
    pass


# ── EGTP-IMT Pricing ─────────────────────────────────────────────────────────
IMT_PRICES = {
    ("standard",   "simple"):     2500.0,
    ("standard",   "duplicate"):  4500.0,
    ("standard",   "triplicate"): 6500.0,
    ("pathogenic", "simple"):     4000.0,
    ("pathogenic", "duplicate"):  7000.0,
    ("pathogenic", "triplicate"): 10000.0,
}

def calculate_imt(sample_type: str, analysis_mode: str,
                  disposable_target: bool = False) -> dict:
    """
    sample_type:   'standard' | 'pathogenic'
    analysis_mode: 'simple' | 'duplicate' | 'triplicate'
    disposable_target: True if pathogenic (mandatory, adds surcharge)
    """
    key = (sample_type.lower(), analysis_mode.lower())
    if key not in IMT_PRICES:
        raise PricingError(
            f"Invalid IMT combination: type='{sample_type}', mode='{analysis_mode}'.")
    base = IMT_PRICES[key]
    target_surcharge = 500.0 if disposable_target else 0.0
    total = base + target_surcharge
    return {
        "service_code":       "EGTP-IMT",
        "sample_type":        sample_type,
        "analysis_mode":      analysis_mode,
        "base_price":         base,
        "disposable_target":  target_surcharge,
        "total_dzd":          total,
        "breakdown": [
            {"label": f"MALDI-TOF ({sample_type}, {analysis_mode})", "amount": base},
            {"label": "Disposable MALDI target plate", "amount": target_surcharge},
        ]
    }


# ── EGTP-SeqS Pricing ────────────────────────────────────────────────────────
SEQS_PRICES = {
    "F":       5500.0,
    "F+R":    10500.0,
    "F+R_long": 12000.0,
}

def calculate_seqs(direction: str) -> dict:
    """
    direction: 'F' | 'F+R' | 'F+R_long'
    PCR is NOT included — client provides amplicons.
    """
    if direction not in SEQS_PRICES:
        raise PricingError(
            f"Invalid SeqS direction: '{direction}'. Use F / F+R / F+R_long.")
    base = SEQS_PRICES[direction]
    return {
        "service_code":  "EGTP-SeqS",
        "direction":     direction,
        "sequencing":    base,
        "pcr_included":  False,
        "dna_extraction_included": False,
        "total_dzd":     base,
        "breakdown": [
            {"label": f"Sanger sequencing ({direction})", "amount": base},
        ]
    }


# ── EGTP-Seq01 Pricing ───────────────────────────────────────────────────────
SEQ01_SEQ_PRICES = {"F": 5500.0, "F+R": 10500.0, "F+R_long": 12000.0}
PCR_COST         = 1500.0
DNA_EXTR_COST    = 1000.0
LYOPH_ADDON      = 2000.0
PRIMER_DESIGN    = {"none": 0.0, "simple": 2000.0, "moderate": 3500.0, "complex": 5000.0}

def calculate_seq01(direction: str,
                    addon_lyophilisation: bool = False,
                    addon_primer_design: str = "none") -> dict:
    """
    direction: 'F' | 'F+R' | 'F+R_long'
    Includes PCR (1,500 DZD). DNA extraction NOT included.
    """
    if direction not in SEQ01_SEQ_PRICES:
        raise PricingError(f"Invalid Seq01 direction: '{direction}'.")
    if addon_primer_design not in PRIMER_DESIGN:
        raise PricingError(f"Invalid primer design option: '{addon_primer_design}'.")

    seq_cost    = SEQ01_SEQ_PRICES[direction]
    lyoph_cost  = LYOPH_ADDON if addon_lyophilisation else 0.0
    design_cost = PRIMER_DESIGN[addon_primer_design]
    total       = seq_cost + PCR_COST + lyoph_cost + design_cost

    return {
        "service_code":          "EGTP-Seq01",
        "direction":             direction,
        "sequencing":            seq_cost,
        "pcr":                   PCR_COST,
        "lyophilisation_addon":  lyoph_cost,
        "primer_design_addon":   design_cost,
        "total_dzd":             total,
        "breakdown": [
            {"label": f"Sanger sequencing ({direction})",         "amount": seq_cost},
            {"label": "PCR amplification",                        "amount": PCR_COST},
            {"label": "Lyophilisation add-on",                    "amount": lyoph_cost},
            {"label": f"Primer design ({addon_primer_design})",   "amount": design_cost},
        ]
    }


# ── EGTP-Seq02 Pricing ───────────────────────────────────────────────────────
def calculate_seq02(direction: str,
                    addon_lyophilisation: bool = False,
                    addon_primer_design: str = "none") -> dict:
    """
    direction: 'F' | 'F+R' | 'F+R_long'
    Includes PCR (1,500 DZD) + DNA extraction (1,000 DZD).
    """
    if direction not in SEQ01_SEQ_PRICES:
        raise PricingError(f"Invalid Seq02 direction: '{direction}'.")
    if addon_primer_design not in PRIMER_DESIGN:
        raise PricingError(f"Invalid primer design option: '{addon_primer_design}'.")

    seq_cost    = SEQ01_SEQ_PRICES[direction]
    lyoph_cost  = LYOPH_ADDON if addon_lyophilisation else 0.0
    design_cost = PRIMER_DESIGN[addon_primer_design]
    total       = seq_cost + PCR_COST + DNA_EXTR_COST + lyoph_cost + design_cost

    return {
        "service_code":          "EGTP-Seq02",
        "direction":             direction,
        "sequencing":            seq_cost,
        "pcr":                   PCR_COST,
        "dna_extraction":        DNA_EXTR_COST,
        "lyophilisation_addon":  lyoph_cost,
        "primer_design_addon":   design_cost,
        "total_dzd":             total,
        "breakdown": [
            {"label": f"Sanger sequencing ({direction})",         "amount": seq_cost},
            {"label": "PCR amplification",                        "amount": PCR_COST},
            {"label": "DNA extraction",                           "amount": DNA_EXTR_COST},
            {"label": "Lyophilisation add-on",                    "amount": lyoph_cost},
            {"label": f"Primer design ({addon_primer_design})",   "amount": design_cost},
        ]
    }


# ── EGTP-PCR Pricing ─────────────────────────────────────────────────────────
def calculate_pcr(num_reactions: int = 1) -> dict:
    """Flat 1,500 DZD per reaction."""
    if num_reactions < 1:
        raise PricingError("Number of reactions must be at least 1.")
    total = 1500.0 * num_reactions
    return {
        "service_code":   "EGTP-PCR",
        "reactions":      num_reactions,
        "price_per_rxn":  1500.0,
        "total_dzd":      total,
        "breakdown": [
            {"label": f"PCR × {num_reactions} reaction(s)", "amount": total},
        ]
    }


# ── EGTP-CAN Pricing ─────────────────────────────────────────────────────────
def calculate_can(num_samples: int,
                  gel_requested: bool = False) -> dict:
    """500 DZD/sample spectrophotometry + optional 500 DZD gel."""
    if num_samples < 1:
        raise PricingError("Number of samples must be at least 1.")
    spec_total = 500.0 * num_samples
    gel_total  = 500.0 * num_samples if gel_requested else 0.0
    total      = spec_total + gel_total
    return {
        "service_code":    "EGTP-CAN",
        "num_samples":     num_samples,
        "spectrophotometry": spec_total,
        "gel_electrophoresis": gel_total,
        "total_dzd":       total,
        "breakdown": [
            {"label": f"Spectrophotometry × {num_samples} sample(s)", "amount": spec_total},
            {"label": f"Gel electrophoresis × {num_samples} sample(s)", "amount": gel_total},
        ]
    }


# ── EGTP-GDE Pricing ─────────────────────────────────────────────────────────
def calculate_gde(num_samples: int = 1) -> dict:
    """1,000 DZD per sample."""
    total = 1000.0 * num_samples
    return {
        "service_code": "EGTP-GDE",
        "num_samples":  num_samples,
        "total_dzd":    total,
        "breakdown": [
            {"label": f"DNA extraction × {num_samples} sample(s)", "amount": total},
        ]
    }


# ── EGTP-PS Pricing ──────────────────────────────────────────────────────────
PS_LENGTH_PRICES = {
    "≤25":    8500.0,
    "26-30": 11000.0,
    "31-40": 14000.0,
}

def calculate_ps(primer_length_nt: int,
                 design_complexity: str = "none",
                 num_sets: int = 1) -> dict:
    """
    primer_length_nt: integer 18–40
    design_complexity: 'none' | 'simple' | 'moderate' | 'complex'
    Price per set (F + R primer pair).
    """
    if primer_length_nt < 18 or primer_length_nt > 40:
        raise PricingError(
            f"Primer length {primer_length_nt} nt out of range (18–40 nt).")
    if design_complexity not in PRIMER_DESIGN:
        raise PricingError(f"Invalid design complexity: '{design_complexity}'.")

    if primer_length_nt <= 25:
        length_key, synth_price = "≤25", 8500.0
    elif primer_length_nt <= 30:
        length_key, synth_price = "26-30", 11000.0
    else:
        length_key, synth_price = "31-40", 14000.0

    design_cost    = PRIMER_DESIGN[design_complexity]
    total_per_set  = synth_price + design_cost
    total          = total_per_set * num_sets

    return {
        "service_code":      "EGTP-PS",
        "primer_length_nt":  primer_length_nt,
        "length_category":   length_key,
        "num_sets":          num_sets,
        "synthesis_per_set": synth_price,
        "design_per_set":    design_cost,
        "total_per_set":     total_per_set,
        "total_dzd":         total,
        "breakdown": [
            {"label": f"Primer synthesis ({length_key} nt) × {num_sets} set(s)",
             "amount": synth_price * num_sets},
            {"label": f"Primer design ({design_complexity}) × {num_sets} set(s)",
             "amount": design_cost * num_sets},
        ]
    }


# ── EGTP-Lyoph Pricing ───────────────────────────────────────────────────────
LYOPH_MODE_RATES = {
    "primary":   3000.0,
    "secondary": 4000.0,
}

def calculate_lyoph(volume_ml: float,
                    drying_mode: str,
                    cycles_24h: int,
                    num_samples: int = 1) -> dict:
    """
    volume_ml:   float — actual sample volume per container
    drying_mode: 'primary' | 'secondary'
    cycles_24h:  int ≥ 1 — total 24h cycles required
    Pricing: volume_factor × mode_rate × cycles × num_samples
    Volume factor: proportional to 40 mL reference (base unit).
    """
    if drying_mode not in LYOPH_MODE_RATES:
        raise PricingError(
            f"Invalid drying mode: '{drying_mode}'. Use 'primary' or 'secondary'.")
    if volume_ml <= 0:
        raise PricingError("Volume must be greater than 0 mL.")
    if cycles_24h < 1:
        raise PricingError("Cycles must be at least 1 (minimum 24h).")

    BASE_VOLUME    = 40.0
    mode_rate      = LYOPH_MODE_RATES[drying_mode]
    volume_factor  = max(1.0, volume_ml / BASE_VOLUME)
    cost_per_sample = round(mode_rate * volume_factor * cycles_24h, 2)
    total          = round(cost_per_sample * num_samples, 2)

    return {
        "service_code":    "EGTP-Lyoph",
        "volume_ml":       volume_ml,
        "volume_factor":   round(volume_factor, 3),
        "drying_mode":     drying_mode,
        "cycles_24h":      cycles_24h,
        "mode_rate_dzd":   mode_rate,
        "cost_per_sample": cost_per_sample,
        "num_samples":     num_samples,
        "total_dzd":       total,
        "breakdown": [
            {"label": f"{drying_mode.capitalize()} lyophilisation — "
                      f"{volume_ml}mL × {cycles_24h} cycle(s) × {num_samples} sample(s)",
             "amount": total},
        ]
    }


# ── EGTP-WGS Pricing ─────────────────────────────────────────────────────────
def calculate_wgs(organism_complexity: str = "standard",
                  bioinformatics_required: bool = False) -> dict:
    """
    organism_complexity: 'standard' | 'complex' (fungi, large genomes)
    Bioinformatics is quoted separately — not calculated here.
    """
    base = 85000.0
    complexity_surcharge = 15000.0 if organism_complexity == "complex" else 0.0
    total = base + complexity_surcharge

    return {
        "service_code":            "EGTP-Illumina-Microbial-WGS",
        "organism_complexity":     organism_complexity,
        "base_price":              base,
        "complexity_surcharge":    complexity_surcharge,
        "bioinformatics_required": bioinformatics_required,
        "bioinformatics_note":     "Quoted separately upon request" if bioinformatics_required else "Not requested",
        "total_dzd":               total,
        "breakdown": [
            {"label": "Illumina MiSeq WGS (standard bacterial coverage)", "amount": base},
            {"label": "Complex genome surcharge (fungi/large)",            "amount": complexity_surcharge},
        ]
    }


# ── Universal price calculator dispatcher ────────────────────────────────────
CALCULATORS = {
    "svc-egtp-imt":   lambda p: calculate_imt(**p),
    "svc-egtp-seq01": lambda p: calculate_seq01(**p),
    "svc-egtp-seq02": lambda p: calculate_seq02(**p),
    "svc-egtp-seqs":  lambda p: calculate_seqs(**p),
    "svc-egtp-pcr":   lambda p: calculate_pcr(**p),
    "svc-egtp-can":   lambda p: calculate_can(**p),
    "svc-egtp-gde":   lambda p: calculate_gde(**p),
    "svc-egtp-ps":    lambda p: calculate_ps(**p),
    "svc-egtp-lyoph": lambda p: calculate_lyoph(**p),
    "svc-egtp-wgs":   lambda p: calculate_wgs(**p),
}

def calculate_price(service_id: str, pricing_params: dict) -> dict:
    calc = CALCULATORS.get(service_id)
    if not calc:
        raise PricingError(f"No pricing calculator for service: {service_id}")
    return calc(pricing_params)


def render_price_breakdown(result: dict) -> str:
    """Returns a readable breakdown string for display."""
    lines = [f"**{result['service_code']} — Price Breakdown**"]
    for item in result.get("breakdown", []):
        if item["amount"] > 0:
            lines.append(f"- {item['label']}: **{item['amount']:,.0f} DZD**")
    lines.append(f"---")
    lines.append(f"**TOTAL: {result['total_dzd']:,.0f} DZD**")
    return "\n".join(lines)