"""
PLAGENOR Service Forms
Per-service dynamic forms matching official IBTIKAR-DGRSDT DOCX templates.
Each form collects all mandatory and optional fields per service.
Business logic: ZERO. All pricing routed through service_pricing_engine.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from datetime import date
from core.service_pricing_engine import (
    calculate_imt, calculate_seq01, calculate_seq02, calculate_seqs,
    calculate_pcr, calculate_can, calculate_gde, calculate_ps,
    calculate_lyoph, calculate_wgs, render_price_breakdown,
)

# ── Shared requester section (common to all forms) ───────────────────────────
def _requester_section(user: dict) -> dict:
    st.markdown("### 👤 Section 1 — Requester Information")
    col1, col2 = st.columns(2)
    with col1:
        full_name = st.text_input(
            "Full Name *",
            value=user.get("full_name", ""),
            key="req_fullname")
        institution = st.text_input(
            "University / Institution *",
            value=user.get("organization_id", ""),
            key="req_institution")
        laboratory = st.text_input("Laboratory *", key="req_lab")
    with col2:
        function = st.selectbox(
            "Function / Position *",
            ["PhD Student", "Researcher", "MCB", "MCA", "Professor",
             "Engineer", "Technician", "Other"],
            key="req_function")
        email = st.text_input(
            "Email *",
            value=user.get("email", ""),
            key="req_email")
        phone = st.text_input("Phone Number *", key="req_phone")
    return {
        "full_name":    full_name,
        "institution":  institution,
        "laboratory":   laboratory,
        "function":     function,
        "email":        email,
        "phone":        phone,
    }


def _analysis_section() -> dict:
    st.markdown("### 📋 Section 2 — Analysis Request Information")
    col1, col2 = st.columns(2)
    with col1:
        analysis_frame = st.selectbox(
            "Analysis Framework *",
            ["PhD Thesis", "Research Project", "Master Thesis",
             "Industrial Contract", "Other"],
            key="analysis_frame")
        project_title = st.text_input("Project Title *", key="project_title")
    with col2:
        director = st.text_input(
            "Research Director / Project Leader *",
            key="project_director")
    return {
        "analysis_frame": analysis_frame,
        "project_title":  project_title,
        "director":       director,
    }


def _ethical_declaration(service_code: str) -> bool:
    st.markdown("---")
    st.markdown("### ⚖️ Ethical Responsibility Declaration")
    st.warning(
        "By submitting this form, the applicant certifies that all samples were "
        "collected, handled, and transferred in strict compliance with applicable "
        "ethical and regulatory standards. The applicant assumes full responsibility "
        "for the nature, origin, and use of the samples."
    )
    signed = st.checkbox(
        f"✅ I have read and accept the ethical responsibility declaration for {service_code} *",
        key=f"ethical_{service_code}")
    return signed


def _biosafety_section(key_prefix: str) -> dict:
    st.markdown("#### 🔴 Biosafety Declaration (Mandatory for Pathogenic/Clinical Samples)")
    is_pathogenic = st.checkbox(
        "This submission contains pathogenic or clinical isolates *",
        key=f"{key_prefix}_is_pathogenic")
    biosafety_level = None
    if is_pathogenic:
        st.error(
            "⚠️ Biosafety declaration required. Undeclared biological risk will "
            "result in automatic rejection.")
        biosafety_level = st.selectbox(
            "Biosafety Level *",
            ["BSL-1", "BSL-2", "BSL-3"],
            key=f"{key_prefix}_bsl")
        st.info(
            "Compliant transport required per ADR 6.2, IATA DGR, "
            "and Directive 2000/54/CE.")
    return {
        "is_pathogenic":   is_pathogenic,
        "biosafety_level": biosafety_level,
    }


def _render_price_box(result: dict):
    breakdown_md = render_price_breakdown(result)
    st.markdown(f"""
    <div style="
        background: linear-gradient(135deg, #1B4F72, #154360);
        color: white; border-radius: 14px; padding: 20px 24px;
        margin: 16px 0;
    ">
        <div style="font-size:0.8rem;text-transform:uppercase;
                    letter-spacing:1px;opacity:0.75;margin-bottom:8px;">
            Estimated Cost
        </div>
        <div style="font-size:2.2rem;font-weight:800;">
            {result['total_dzd']:,.0f} DZD
        </div>
        <div style="font-size:0.8rem;opacity:0.7;margin-top:6px;">
            Subject to final admin validation
        </div>
    </div>
    """, unsafe_allow_html=True)
    with st.expander("📊 View detailed breakdown"):
        for item in result.get("breakdown", []):
            if item["amount"] > 0:
                col1, col2 = st.columns([3, 1])
                col1.write(item["label"])
                col2.write(f"**{item['amount']:,.0f} DZD**")


# ── EGTP-IMT Form ─────────────────────────────────────────────────────────────
def form_egtp_imt(user: dict) -> dict:
    st.markdown("## 🔬 EGTP-IMT — MALDI-TOF Microbial Identification")
    st.info("Version V02 · 02.11.2025 · IBTIKAR / PLAGENOR-ESSBO")

    requester = _requester_section(user)
    analysis  = _analysis_section()
    biosafety = _biosafety_section("imt")

    st.markdown("### 🧫 Section 3 — Sample Information")
    st.warning(
        "🔴 Cultures must be fresh, pure, in exponential growth phase, on "
        "appropriate solid agar (2% agar, 20 g/L). Deliver within 24h at 4–8°C.")

    samples = []
    num_samples = st.number_input(
        "Number of isolates *", min_value=1, max_value=20, value=1, key="imt_n")
    for i in range(int(num_samples)):
        with st.expander(f"Isolate #{i+1}", expanded=(i == 0)):
            c1, c2 = st.columns(2)
            with c1:
                code = st.text_input(
                    f"Internal sample code * #{i+1}", key=f"imt_code_{i}")
                org_type = st.selectbox(
                    f"Organism type * #{i+1}",
                    ["Bacterium", "Yeast", "Mould"],
                    key=f"imt_org_{i}")
                source = st.selectbox(
                    f"Source of isolation * #{i+1}",
                    ["Environmental", "Food", "Clinical",
                     "Industrial", "Agricultural", "Other"],
                    key=f"imt_src_{i}")
                date_isolation = st.date_input(
                    f"Date of isolation * #{i+1}",
                    key=f"imt_date_{i}")
            with c2:
                medium = st.text_input(
                    f"Culture medium * #{i+1}",
                    placeholder="e.g. TSA, Sabouraud",
                    key=f"imt_med_{i}")
                temperature = st.number_input(
                    f"Culture temperature (°C) * #{i+1}",
                    min_value=4.0, max_value=60.0, value=37.0,
                    key=f"imt_temp_{i}")
                respiration = st.selectbox(
                    f"Respiratory type * #{i+1}",
                    ["Aerobic", "Anaerobic", "Microaerophilic", "Facultative"],
                    key=f"imt_resp_{i}")
                incubation = st.text_input(
                    f"Incubation time * #{i+1}",
                    placeholder="e.g. 24h, 48h",
                    key=f"imt_inc_{i}")
            remarks = st.text_input(
                f"Remarks #{i+1}", key=f"imt_rem_{i}")
            samples.append({
                "code": code, "organism_type": org_type, "source": source,
                "date_isolation": str(date_isolation), "medium": medium,
                "temperature": temperature, "respiration": respiration,
                "incubation": incubation, "remarks": remarks,
            })

    st.markdown("### ⚙️ Section 4 — Analysis Options")
    fresh_culture = st.checkbox(
        "I can provide fresh cultures (mandatory for reliable results) *",
        key="imt_fresh")
    if not fresh_culture:
        st.warning(
            "PLAGENOR can perform purification and subculturing — "
            "additional charges will apply.")

    maldi_target = st.selectbox(
        "MALDI target type *",
        ["Standard reusable target", "Disposable single-use target (mandatory for pathogens)"],
        key="imt_target")
    disposable = "Disposable" in maldi_target or biosafety["is_pathogenic"]

    analysis_mode = st.selectbox(
        "Analysis mode *",
        ["simple", "duplicate", "triplicate"],
        format_func=lambda x: {
            "simple": "Simple (×1)", "duplicate": "Duplicate (×2)",
            "triplicate": "Triplicate (×3)"
        }[x],
        key="imt_mode")

    sample_category = "pathogenic" if biosafety["is_pathogenic"] else "standard"

    try:
        pricing = calculate_imt(sample_category, analysis_mode, disposable)
        total_price = pricing["total_dzd"] * int(num_samples)
        pricing["total_dzd"] = total_price
        pricing["num_samples"] = int(num_samples)
        _render_price_box(pricing)
    except Exception as e:
        st.error(f"Pricing error: {e}")
        pricing = {}

    ethical = _ethical_declaration("EGTP-IMT")

    return {
        "service_code":    "EGTP-IMT",
        "service_id":      "svc-egtp-imt",
        "requester":       requester,
        "analysis_info":   analysis,
        "biosafety":       biosafety,
        "samples":         samples,
        "fresh_culture":   fresh_culture,
        "analysis_mode":   analysis_mode,
        "maldi_target":    maldi_target,
        "disposable":      disposable,
        "pricing":         pricing,
        "ethical_signed":  ethical,
        "estimated_budget": pricing.get("total_dzd", 0.0),
    }


# ── EGTP-Seq01 Form ───────────────────────────────────────────────────────────
def form_egtp_seq01(user: dict) -> dict:
    st.markdown("## 🧬 EGTP-Seq01 — Molecular Identification via Sequencing (PCR + Seq)")
    st.info("Version V01 · IBTIKAR / PLAGENOR-ESSBO · Includes PCR (1,500 DZD)")

    requester = _requester_section(user)
    analysis  = _analysis_section()

    st.markdown("### 🧪 Section 3 — Sample Information")
    st.warning(
        "Pure recent culture (preferred) OR extracted DNA: "
        "A260/280 ≈ 1.8–2.0, ≥10 ng/µL, ≥20 µL.")

    samples = []
    num_samples = st.number_input(
        "Number of samples *", min_value=1, max_value=20, value=1, key="seq01_n")
    for i in range(int(num_samples)):
        with st.expander(f"Sample #{i+1}", expanded=(i == 0)):
            c1, c2 = st.columns(2)
            with c1:
                code = st.text_input(f"Sample code * #{i+1}", key=f"seq01_code_{i}")
                org_type = st.selectbox(
                    f"Organism type * #{i+1}",
                    ["Bacterium", "Archaea", "Fungi", "Plant", "Animal", "Other"],
                    key=f"seq01_org_{i}")
                source = st.text_input(
                    f"Source of isolation * #{i+1}", key=f"seq01_src_{i}")
                date_isolation = st.date_input(
                    f"Date of isolation/extraction * #{i+1}", key=f"seq01_date_{i}")
            with c2:
                medium = st.text_input(
                    f"Culture medium * #{i+1}", key=f"seq01_med_{i}")
                temperature = st.number_input(
                    f"Temperature (°C) * #{i+1}",
                    min_value=4.0, max_value=60.0, value=37.0,
                    key=f"seq01_temp_{i}")
                respiration = st.selectbox(
                    f"Respiratory type * #{i+1}",
                    ["Aerobic", "Anaerobic", "Microaerophilic", "Facultative"],
                    key=f"seq01_resp_{i}")
                incubation = st.text_input(
                    f"Incubation time * #{i+1}", key=f"seq01_inc_{i}")
            remarks = st.text_input(f"Remarks #{i+1}", key=f"seq01_rem_{i}")
            samples.append({
                "code": code, "organism_type": org_type, "source": source,
                "date": str(date_isolation), "medium": medium,
                "temperature": temperature, "respiration": respiration,
                "incubation": incubation, "remarks": remarks,
            })

    st.markdown("### ⚙️ Section 4 — Sequencing Options")
    c1, c2 = st.columns(2)
    with c1:
        direction = st.selectbox(
            "Sequencing direction *",
            ["F", "F+R", "F+R_long"],
            format_func=lambda x: {
                "F":        "Forward only (F) — 7,000 DZD",
                "F+R":      "Forward + Reverse (F+R) — 12,000 DZD",
                "F+R_long": "F+R long/high-GC/re-run — 13,500 DZD"
            }[x],
            key="seq01_dir")
        target_region = st.selectbox(
            "Target region *",
            ["16S rRNA (bacteria)", "ITS (fungi)", "18S rRNA (eukaryotes)",
             "Other (specify in remarks)"],
            key="seq01_target")
    with c2:
        addon_lyoph = st.checkbox(
            "Lyophilisation add-on (+2,000 DZD/sample, fungal samples)",
            key="seq01_lyoph")
        addon_design = st.selectbox(
            "Primer design (if required)",
            ["none", "simple", "moderate", "complex"],
            format_func=lambda x: {
                "none":     "Not required",
                "simple":   "Simple template (+2,000 DZD)",
                "moderate": "Moderate complexity (+3,000–4,000 DZD)",
                "complex":  "Complex/large genome (+5,000 DZD)"
            }[x],
            key="seq01_design")

    try:
        pricing_per = calculate_seq01(direction, addon_lyoph, addon_design)
        pricing_per["total_dzd"] = pricing_per["total_dzd"] * int(num_samples)
        pricing_per["num_samples"] = int(num_samples)
        _render_price_box(pricing_per)
    except Exception as e:
        st.error(f"Pricing error: {e}")
        pricing_per = {}

    ethical = _ethical_declaration("EGTP-Seq01")

    return {
        "service_code":      "EGTP-Seq01",
        "service_id":        "svc-egtp-seq01",
        "requester":         requester,
        "analysis_info":     analysis,
        "samples":           samples,
        "direction":         direction,
        "target_region":     target_region,
        "addon_lyoph":       addon_lyoph,
        "addon_design":      addon_design,
        "pricing":           pricing_per,
        "ethical_signed":    ethical,
        "estimated_budget":  pricing_per.get("total_dzd", 0.0),
    }


# ── EGTP-Seq02 Form ───────────────────────────────────────────────────────────
def form_egtp_seq02(user: dict) -> dict:
    st.markdown("## 🧬 EGTP-Seq02 — Microbial ID via Sequencing (DNA Extraction + PCR + Seq)")
    st.info("Version V01 · Includes DNA extraction (1,000 DZD) + PCR (1,500 DZD)")

    requester = _requester_section(user)
    analysis  = _analysis_section()
    biosafety = _biosafety_section("seq02")

    st.markdown("### 🧪 Section 3 — Sample Information")
    st.warning(
        "Provide pure recent cultures or suitable biomass/tissue. "
        "Minimum quantities: 2g tissue, 10mL microbial culture, or 2mL blood.")

    samples = []
    num_samples = st.number_input(
        "Number of samples *", min_value=1, max_value=20, value=1, key="seq02_n")
    for i in range(int(num_samples)):
        with st.expander(f"Sample #{i+1}", expanded=(i == 0)):
            c1, c2 = st.columns(2)
            with c1:
                code = st.text_input(f"Sample code * #{i+1}", key=f"seq02_code_{i}")
                sample_type = st.selectbox(
                    f"Sample type * #{i+1}",
                    ["Bacterium", "Blood", "Animal tissue", "Plant tissue",
                     "Environmental", "Other"],
                    key=f"seq02_type_{i}")
                collection_date = st.date_input(
                    f"Collection/isolation date * #{i+1}", key=f"seq02_date_{i}")
                volume_ul = st.number_input(
                    f"Volume (µL) #{i+1}", min_value=0.0, key=f"seq02_vol_{i}")
            with c2:
                quantity_g = st.number_input(
                    f"Quantity (g) #{i+1}", min_value=0.0, key=f"seq02_qty_{i}")
                storage_cond = st.selectbox(
                    f"Storage conditions #{i+1}",
                    ["-80°C", "-20°C", "4°C", "Room temperature"],
                    key=f"seq02_stor_{i}")
                sample_state = st.selectbox(
                    f"Sample state #{i+1}",
                    ["Fresh culture", "Frozen", "Fixed", "Lyophilised", "Other"],
                    key=f"seq02_state_{i}")
            remarks = st.text_input(f"Remarks #{i+1}", key=f"seq02_rem_{i}")
            samples.append({
                "code": code, "sample_type": sample_type,
                "collection_date": str(collection_date),
                "volume_ul": volume_ul, "quantity_g": quantity_g,
                "storage_conditions": storage_cond, "state": sample_state,
                "remarks": remarks,
            })

    if biosafety["is_pathogenic"]:
        st.error(
            "⚠️ MANDATORY: Attach a recent serology report confirming "
            "absence/presence of known pathogens (HIV, hepatitis, brucellosis, etc.).")

    st.markdown("### ⚙️ Section 4 — Analysis Options")
    c1, c2 = st.columns(2)
    with c1:
        extraction_method = st.selectbox(
            "DNA extraction method *",
            ["Classical method", "Commercial kit"],
            key="seq02_extr")
        pcr_kit = st.selectbox(
            "PCR kit *",
            ["DreamTaq (standard)", "Phusion (high-fidelity)",
             "KAPA HiFi", "Other"],
            key="seq02_kit")
        qc_method = st.selectbox(
            "Quality control technique *",
            ["ScanDrop spectrophotometry",
             "ScanDrop + Gel electrophoresis",
             "Fluorometry (Qubit)"],
            key="seq02_qc")
    with c2:
        direction = st.selectbox(
            "Sequencing direction *",
            ["F", "F+R", "F+R_long"],
            format_func=lambda x: {
                "F":        "Forward only (F) — 8,000 DZD",
                "F+R":      "Forward + Reverse (F+R) — 13,000 DZD",
                "F+R_long": "F+R long/high-GC/re-run — 14,500 DZD"
            }[x],
            key="seq02_dir")
        addon_lyoph = st.checkbox(
            "Lyophilisation add-on (+2,000 DZD, fungal samples)",
            key="seq02_lyoph")
        addon_design = st.selectbox(
            "Primer design",
            ["none", "simple", "moderate", "complex"],
            format_func=lambda x: {
                "none": "Not required",
                "simple": "Simple (+2,000 DZD)",
                "moderate": "Moderate (+3,000–4,000 DZD)",
                "complex": "Complex (+5,000 DZD)"
            }[x],
            key="seq02_design")
        gel_marker = st.selectbox(
            "Gel marker (if electrophoresis)",
            ["100 bp", "1 kb", "Other"],
            key="seq02_marker")

    try:
        pricing = calculate_seq02(direction, addon_lyoph, addon_design)
        pricing["total_dzd"] = pricing["total_dzd"] * int(num_samples)
        pricing["num_samples"] = int(num_samples)
        _render_price_box(pricing)
    except Exception as e:
        st.error(f"Pricing error: {e}")
        pricing = {}

    ethical = _ethical_declaration("EGTP-Seq02")

    return {
        "service_code":       "EGTP-Seq02",
        "service_id":         "svc-egtp-seq02",
        "requester":          requester,
        "analysis_info":      analysis,
        "biosafety":          biosafety,
        "samples":            samples,
        "extraction_method":  extraction_method,
        "pcr_kit":            pcr_kit,
        "qc_method":          qc_method,
        "direction":          direction,
        "gel_marker":         gel_marker,
        "addon_lyoph":        addon_lyoph,
        "addon_design":       addon_design,
        "pricing":            pricing,
        "ethical_signed":     ethical,
        "estimated_budget":   pricing.get("total_dzd", 0.0),
    }


# ── EGTP-SeqS Form ────────────────────────────────────────────────────────────
def form_egtp_seqs(user: dict) -> dict:
    st.markdown("## 🧬 EGTP-SeqS — DNA Sequencing via Sanger Method")
    st.info("Sequencing only — PCR NOT included. Client must provide amplicons.")

    requester = _requester_section(user)
    analysis  = _analysis_section()

    st.markdown("### 🧪 Section 3 — Amplicon Information")
    st.error(
        "⚠️ You MUST provide: (1) pure high-quality PCR amplicons, "
        "(2) QC results for amplicons, (3) appropriate sequencing primers.")

    amplicons_provided = st.checkbox(
        "✅ I confirm I will provide pure PCR amplicons *",
        key="seqs_ampl")
    qc_provided = st.checkbox(
        "✅ I confirm QC results for amplicons will be included *",
        key="seqs_qc")
    primers_provided = st.checkbox(
        "✅ I confirm sequencing primers will be provided *",
        key="seqs_prim")

    if not (amplicons_provided and qc_provided and primers_provided):
        st.warning(
            "All three confirmations are required to submit EGTP-SeqS.")

    samples = []
    num_samples = st.number_input(
        "Number of samples *", min_value=1, max_value=20, value=1, key="seqs_n")
    for i in range(int(num_samples)):
        with st.expander(f"Sample #{i+1}", expanded=(i == 0)):
            code = st.text_input(f"Sample code * #{i+1}", key=f"seqs_code_{i}")
            remarks = st.text_input(f"Remarks #{i+1}", key=f"seqs_rem_{i}")
            samples.append({"code": code, "remarks": remarks})

    direction = st.selectbox(
        "Sequencing direction *",
        ["F", "F+R", "F+R_long"],
        format_func=lambda x: {
            "F":        "Forward only (F) — 5,500 DZD",
            "F+R":      "Forward + Reverse (F+R) — 10,500 DZD",
            "F+R_long": "F+R long/high-GC/re-run — 12,000 DZD"
        }[x],
        key="seqs_dir")

    try:
        pricing = calculate_seqs(direction)
        pricing["total_dzd"] = pricing["total_dzd"] * int(num_samples)
        pricing["num_samples"] = int(num_samples)
        _render_price_box(pricing)
    except Exception as e:
        st.error(f"Pricing error: {e}")
        pricing = {}

    ethical = _ethical_declaration("EGTP-SeqS")

    return {
        "service_code":         "EGTP-SeqS",
        "service_id":           "svc-egtp-seqs",
        "requester":            requester,
        "analysis_info":        analysis,
        "samples":              samples,
        "amplicons_provided":   amplicons_provided,
        "qc_provided":          qc_provided,
        "primers_provided":     primers_provided,
        "direction":            direction,
        "pricing":              pricing,
        "ethical_signed":       ethical,
        "estimated_budget":     pricing.get("total_dzd", 0.0),
    }


# ── EGTP-PCR Form ─────────────────────────────────────────────────────────────
def form_egtp_pcr(user: dict) -> dict:
    st.markdown("## 🔬 EGTP-PCR — PCR Amplification")
    st.info("1,500 DZD per reaction · Flat rate")

    requester = _requester_section(user)
    analysis  = _analysis_section()

    st.markdown("### 🧪 Section 3 — Sample & Reaction Information")
    num_reactions = st.number_input(
        "Number of reactions *", min_value=1, max_value=50, value=1, key="pcr_n")

    samples = []
    for i in range(int(num_reactions)):
        with st.expander(f"Reaction #{i+1}", expanded=(i == 0)):
            c1, c2 = st.columns(2)
            with c1:
                code = st.text_input(f"Internal code * #{i+1}", key=f"pcr_code_{i}")
                dna_type = st.selectbox(
                    f"DNA type * #{i+1}",
                    ["Chromosomal", "Plasmidic", "cDNA", "Other"],
                    key=f"pcr_dnatype_{i}")
                extr_method = st.text_input(
                    f"Extraction method * #{i+1}", key=f"pcr_extr_{i}")
                target_gene = st.text_input(
                    f"Target gene * #{i+1}", key=f"pcr_gene_{i}")
                amplicon_size = st.number_input(
                    f"Expected amplicon size (bp) * #{i+1}",
                    min_value=50, max_value=10000, value=500,
                    key=f"pcr_size_{i}")
            with c2:
                primer_f = st.text_input(
                    f"Forward primer sequence (5'→3') * #{i+1}",
                    key=f"pcr_pf_{i}")
                primer_r = st.text_input(
                    f"Reverse primer sequence (5'→3') * #{i+1}",
                    key=f"pcr_pr_{i}")
                primer_tm = st.number_input(
                    f"Primer Tm (°C) * #{i+1}",
                    min_value=40.0, max_value=75.0, value=60.0,
                    key=f"pcr_tm_{i}")
                template_vol = st.number_input(
                    f"Template DNA volume (µL) * #{i+1}",
                    min_value=10.0, max_value=50.0, value=10.0,
                    key=f"pcr_tvol_{i}")
                template_conc = st.number_input(
                    f"Template concentration (ng/µL) * #{i+1}",
                    min_value=50.0, max_value=300.0, value=100.0,
                    key=f"pcr_tconc_{i}")
            remarks = st.text_input(f"Remarks #{i+1}", key=f"pcr_rem_{i}")
            samples.append({
                "code": code, "dna_type": dna_type, "extraction_method": extr_method,
                "target_gene": target_gene, "amplicon_size_bp": amplicon_size,
                "primer_forward": primer_f, "primer_reverse": primer_r,
                "primer_tm": primer_tm, "template_volume_ul": template_vol,
                "template_concentration": template_conc, "remarks": remarks,
            })

    try:
        pricing = calculate_pcr(int(num_reactions))
        _render_price_box(pricing)
    except Exception as e:
        st.error(f"Pricing error: {e}")
        pricing = {}

    ethical = _ethical_declaration("EGTP-PCR")

    return {
        "service_code":     "EGTP-PCR",
        "service_id":       "svc-egtp-pcr",
        "requester":        requester,
        "analysis_info":    analysis,
        "reactions":        samples,
        "num_reactions":    int(num_reactions),
        "pricing":          pricing,
        "ethical_signed":   ethical,
        "estimated_budget": pricing.get("total_dzd", 0.0),
    }


# ── EGTP-CAN Form ─────────────────────────────────────────────────────────────
def form_egtp_can(user: dict) -> dict:
    st.markdown("## 🧪 EGTP-CAN — Nucleic Acid Quality Control")
    st.info("500 DZD/sample spectrophotometry · +500 DZD optional gel")

    requester = _requester_section(user)
    analysis  = _analysis_section()

    st.markdown("### 🧪 Section 3 — Sample Information")
    st.warning(
        "Minimum: ≥10 µL for spectrophotometry, ≥15 µL if gel required. "
        "Transport at 4°C or on dry ice.")

    samples = []
    num_samples = st.number_input(
        "Number of samples *", min_value=1, max_value=20, value=1, key="can_n")
    for i in range(int(num_samples)):
        with st.expander(f"Sample #{i+1}", expanded=(i == 0)):
            c1, c2 = st.columns(2)
            with c1:
                code = st.text_input(f"Sample code * #{i+1}", key=f"can_code_{i}")
                na_origin = st.text_input(
                    f"Nucleic acid origin * #{i+1}",
                    placeholder="Organism/source",
                    key=f"can_orig_{i}")
                na_type = st.selectbox(
                    f"Nucleic acid type * #{i+1}",
                    ["Chromosomal DNA", "Plasmidic DNA", "Total RNA",
                     "mRNA", "Genomic DNA", "Other"],
                    key=f"can_type_{i}")
            with c2:
                extr_method = st.text_input(
                    f"Extraction method/kit * #{i+1}", key=f"can_extr_{i}")
                extr_date = st.date_input(
                    f"Extraction date * #{i+1}", key=f"can_date_{i}")
            remarks = st.text_input(f"Remarks #{i+1}", key=f"can_rem_{i}")
            samples.append({
                "code": code, "na_origin": na_origin, "na_type": na_type,
                "extraction_method": extr_method,
                "extraction_date": str(extr_date), "remarks": remarks,
            })

    st.markdown("### ⚙️ Section 4 — QC Options")
    gel_requested = st.checkbox(
        "Gel electrophoresis requested (+500 DZD/sample)",
        key="can_gel")
    if gel_requested:
        gel_pct = st.selectbox(
            "Agarose gel percentage",
            ["0.8%", "1%", "1.5%", "2%"],
            key="can_gelpct")
        gel_marker = st.selectbox(
            "Size marker",
            ["100 bp", "1 kb", "Other"],
            key="can_gelmarker")
    downstream = st.selectbox(
        "Intended downstream application *",
        ["PCR", "Sanger sequencing", "WGS / NGS", "Cloning",
         "RT-PCR", "Other"],
        key="can_downstream")

    try:
        pricing = calculate_can(int(num_samples), gel_requested)
        _render_price_box(pricing)
    except Exception as e:
        st.error(f"Pricing error: {e}")
        pricing = {}

    ethical = _ethical_declaration("EGTP-CAN")

    return {
        "service_code":          "EGTP-CAN",
        "service_id":            "svc-egtp-can",
        "requester":             requester,
        "analysis_info":         analysis,
        "samples":               samples,
        "gel_requested":         gel_requested,
        "downstream_application": downstream,
        "pricing":               pricing,
        "ethical_signed":        ethical,
        "estimated_budget":      pricing.get("total_dzd", 0.0),
    }


# ── EGTP-GDE Form ─────────────────────────────────────────────────────────────
def form_egtp_gde(user: dict) -> dict:
    st.markdown("## 🧬 EGTP-GDE — Genomic DNA Extraction")
    st.info("1,000 DZD per sample · Flat rate")

    requester = _requester_section(user)
    analysis  = _analysis_section()
    biosafety = _biosafety_section("gde")

    st.markdown("### 🧪 Section 3 — Sample Information")

    samples = []
    num_samples = st.number_input(
        "Number of samples *", min_value=1, max_value=20, value=1, key="gde_n")
    for i in range(int(num_samples)):
        with st.expander(f"Sample #{i+1}", expanded=(i == 0)):
            c1, c2 = st.columns(2)
            with c1:
                code = st.text_input(f"Sample code * #{i+1}", key=f"gde_code_{i}")
                sample_type = st.selectbox(
                    f"Sample type * #{i+1}",
                    ["Microbial culture", "Blood", "Animal tissue",
                     "Plant tissue", "Environmental", "Other"],
                    key=f"gde_type_{i}")
                volume_ul = st.number_input(
                    f"Volume (µL) #{i+1}", min_value=0.0, key=f"gde_vol_{i}")
            with c2:
                storage = st.selectbox(
                    f"Storage conditions #{i+1}",
                    ["-80°C", "-20°C", "4°C", "Fresh"],
                    key=f"gde_stor_{i}")
                extraction_kit = st.selectbox(
                    f"Preferred extraction kit #{i+1}",
                    ["Platform standard", "Specific kit (indicate in remarks)"],
                    key=f"gde_kit_{i}")
            remarks = st.text_input(f"Remarks #{i+1}", key=f"gde_rem_{i}")
            samples.append({
                "code": code, "sample_type": sample_type,
                "volume_ul": volume_ul, "storage": storage,
                "extraction_kit": extraction_kit, "remarks": remarks,
            })

    try:
        pricing = calculate_gde(int(num_samples))
        _render_price_box(pricing)
    except Exception as e:
        st.error(f"Pricing error: {e}")
        pricing = {}

    ethical = _ethical_declaration("EGTP-GDE")

    return {
        "service_code":     "EGTP-GDE",
        "service_id":       "svc-egtp-gde",
        "requester":        requester,
        "analysis_info":    analysis,
        "biosafety":        biosafety,
        "samples":          samples,
        "pricing":          pricing,
        "ethical_signed":   ethical,
        "estimated_budget": pricing.get("total_dzd", 0.0),
    }


# ── EGTP-PS Form ──────────────────────────────────────────────────────────────
def form_egtp_ps(user: dict) -> dict:
    st.markdown("## 🧬 EGTP-PS — Primer Synthesis")
    st.info(
        "MerMade 4 phosphoramidite synthesizer · "
        "Butanol desalting · Standard QC included")
    st.warning(
        "⚠️ IMPORTANT: The platform synthesises primers from sequences "
        "provided by the requester. The requester is solely responsible for "
        "verifying sequence accuracy, orientation (5'→3'), specificity, and "
        "thermodynamic properties.")

    requester = _requester_section(user)
    analysis  = _analysis_section()

    st.markdown("### 🧪 Section 3 — Primer Information")
    num_sets = st.number_input(
        "Number of primer sets (F+R pairs) *",
        min_value=1, max_value=20, value=1, key="ps_n")

    primer_sets = []
    for i in range(int(num_sets)):
        with st.expander(f"Primer Set #{i+1}", expanded=(i == 0)):
            c1, c2 = st.columns(2)
            with c1:
                f_name = st.text_input(f"Forward primer name #{i+1}", key=f"ps_fn_{i}")
                f_seq  = st.text_input(
                    f"Forward sequence (5'→3') * #{i+1}", key=f"ps_fs_{i}")
                f_size = st.number_input(
                    f"Forward length (nt) * #{i+1}",
                    min_value=18, max_value=40, value=20, key=f"ps_fl_{i}")
                f_gc   = st.number_input(
                    f"Forward GC% #{i+1}",
                    min_value=0.0, max_value=100.0, value=50.0, key=f"ps_fgc_{i}")
                f_tm   = st.number_input(
                    f"Forward Tm (°C) #{i+1}",
                    min_value=40.0, max_value=75.0, value=60.0, key=f"ps_ftm_{i}")
            with c2:
                r_name = st.text_input(f"Reverse primer name #{i+1}", key=f"ps_rn_{i}")
                r_seq  = st.text_input(
                    f"Reverse sequence (5'→3') * #{i+1}", key=f"ps_rs_{i}")
                r_size = st.number_input(
                    f"Reverse length (nt) * #{i+1}",
                    min_value=18, max_value=40, value=20, key=f"ps_rl_{i}")
                r_gc   = st.number_input(
                    f"Reverse GC% #{i+1}",
                    min_value=0.0, max_value=100.0, value=50.0, key=f"ps_rgc_{i}")
                r_tm   = st.number_input(
                    f"Reverse Tm (°C) #{i+1}",
                    min_value=40.0, max_value=75.0, value=60.0, key=f"ps_rtm_{i}")
            target_gene    = st.text_input(f"Target gene #{i+1}", key=f"ps_tg_{i}")
            accession      = st.text_input(
                f"GenBank accession #{i+1}", key=f"ps_acc_{i}")
            remarks        = st.text_input(f"Remarks #{i+1}", key=f"ps_rem_{i}")
            max_length     = max(int(f_size), int(r_size))
            primer_sets.append({
                "forward_name": f_name, "forward_seq": f_seq, "forward_size": f_size,
                "forward_gc": f_gc, "forward_tm": f_tm,
                "reverse_name": r_name, "reverse_seq": r_seq, "reverse_size": r_size,
                "reverse_gc": r_gc, "reverse_tm": r_tm,
                "target_gene": target_gene, "accession": accession,
                "remarks": remarks, "max_length": max_length,
            })

    st.markdown("### ⚙️ Section 4 — Delivery & Options")
    c1, c2 = st.columns(2)
    with c1:
        delivery_format = st.selectbox(
            "Delivery format *",
            ["1 µM in nuclease-free water (default)", "Dried pellet"],
            key="ps_fmt")
        final_volume = st.text_input(
            "Final volume (µL) and desired concentration",
            placeholder="e.g. 100 µL at 100 µM",
            key="ps_vol")
    with c2:
        design_requested = st.checkbox(
            "Primer design requested (+cost)",
            key="ps_design_req")
        design_complexity = "none"
        if design_requested:
            design_complexity = st.selectbox(
                "Template complexity",
                ["simple", "moderate", "complex"],
                format_func=lambda x: {
                    "simple":   "Simple — small/well-characterised (+2,000 DZD)",
                    "moderate": "Moderate complexity (+3,000–4,000 DZD)",
                    "complex":  "Complex — large/repetitive genome (+5,000 DZD)"
                }[x],
                key="ps_design_cplx")
        advanced_qc = st.checkbox(
            "Advanced QC requested (mass spectrometry — quoted separately)",
            key="ps_advqc")

    try:
        max_len_all = max(s["max_length"] for s in primer_sets) if primer_sets else 20
        pricing = calculate_ps(max_len_all, design_complexity, int(num_sets))
        _render_price_box(pricing)
    except Exception as e:
        st.error(f"Pricing error: {e}")
        pricing = {}

    ethical = _ethical_declaration("EGTP-PS")

    return {
        "service_code":      "EGTP-PS",
        "service_id":        "svc-egtp-ps",
        "requester":         requester,
        "analysis_info":     analysis,
        "primer_sets":       primer_sets,
        "num_sets":          int(num_sets),
        "delivery_format":   delivery_format,
        "final_volume":      final_volume,
        "design_requested":  design_requested,
        "design_complexity": design_complexity,
        "advanced_qc":       advanced_qc,
        "pricing":           pricing,
        "ethical_signed":    ethical,
        "estimated_budget":  pricing.get("total_dzd", 0.0),
    }


# ── EGTP-Lyoph Form ───────────────────────────────────────────────────────────
def form_egtp_lyoph(user: dict) -> dict:
    st.markdown("## ❄️ EGTP-Lyoph — Freeze-Drying (Lyophilisation)")
    st.info("Beta 2-8 LSCplus · ESSBO PLAGENOR · Version V01 · 29.10.2025")

    requester = _requester_section(user)
    analysis  = _analysis_section()
    biosafety = _biosafety_section("lyoph")

    st.markdown("### 🧪 Section 3 — Sample Information")
    st.warning(
        "Use only compatible threaded containers (Erlenmeyer 29/32 recommended). "
        "Max fill: 50% of nominal volume. Optimal fill: 40%.")

    CONTAINER_GUIDE = {
        "Erlenmeyer 50 mL (29/32)":   {"optimal_ml": 20, "max_ml": 25},
        "Erlenmeyer 100 mL (29/32)":  {"optimal_ml": 40, "max_ml": 50},
        "Erlenmeyer 250 mL (29/32)":  {"optimal_ml": 100, "max_ml": 125},
        "Erlenmeyer 500 mL (29/32)":  {"optimal_ml": 200, "max_ml": 250},
        "Microtube 1.5 mL":           {"optimal_ml": 0.6, "max_ml": 0.75},
        "Cryo tube 5 mL":             {"optimal_ml": 2,   "max_ml": 2.5},
        "Glass vial 2-10 mL":         {"optimal_ml": None, "max_ml": None},
        "Other":                      {"optimal_ml": None, "max_ml": None},
    }

    samples = []
    num_samples = st.number_input(
        "Number of samples *", min_value=1, max_value=20, value=1, key="lyoph_n")
    for i in range(int(num_samples)):
        with st.expander(f"Sample #{i+1}", expanded=(i == 0)):
            c1, c2 = st.columns(2)
            with c1:
                code = st.text_input(f"Sample code * #{i+1}", key=f"lyoph_code_{i}")
                sample_type = st.text_input(
                    f"Sample type (bacterium, plant, etc.) * #{i+1}",
                    key=f"lyoph_type_{i}")
                volume_ml = st.number_input(
                    f"Sample volume (mL) * #{i+1}",
                    min_value=0.1, max_value=500.0, value=20.0,
                    key=f"lyoph_vol_{i}")
                container = st.selectbox(
                    f"Container type * #{i+1}",
                    list(CONTAINER_GUIDE.keys()),
                    key=f"lyoph_cont_{i}")
            with c2:
                desiccation = st.selectbox(
                    f"Drying mode * #{i+1}",
                    ["primary", "secondary"],
                    format_func=lambda x: {
                        "primary": "Primary lyophilisation (3,000 DZD/40mL/24h)",
                        "secondary": "Secondary lyophilisation (4,000 DZD/40mL/24h)"
                    }[x],
                    key=f"lyoph_mode_{i}")
                initial_storage = st.selectbox(
                    f"Initial storage conditions #{i+1}",
                    ["-80°C", "-20°C", "4°C", "Room temperature"],
                    key=f"lyoph_stor_{i}")
            remarks = st.text_input(f"Remarks #{i+1}", key=f"lyoph_rem_{i}")
            guide   = CONTAINER_GUIDE[container]
            if guide["max_ml"] and volume_ml > guide["max_ml"]:
                st.error(
                    f"Volume {volume_ml} mL exceeds maximum "
                    f"({guide['max_ml']} mL) for {container}.")
            samples.append({
                "code": code, "sample_type": sample_type, "volume_ml": volume_ml,
                "container": container, "drying_mode": desiccation,
                "initial_storage": initial_storage, "remarks": remarks,
            })

    st.markdown("### ⚙️ Section 4 — Processing Parameters")
    cycles_24h = st.number_input(
        "Estimated lyophilisation cycles (× 24h) *",
        min_value=1, max_value=14, value=2, key="lyoph_cycles")
    if cycles_24h >= 2:
        st.warning(
            f"⚠️ Extended drying: {cycles_24h} × 24h cycles will be billed proportionally.")

    st.markdown("**🚫 Prohibited solvents reminder:**")
    st.error(
        "Do NOT submit samples containing: TFA >10%, formic acid >10%, "
        "halogenated solvents, pure acetone/acetonitrile/methanol, "
        "DMSO >90%, pyridine, or peroxidisable ethers.")

    try:
        if samples:
            avg_vol    = sum(s["volume_ml"] for s in samples) / len(samples)
            main_mode  = samples[0].get("drying_mode", "primary")
            pricing    = calculate_lyoph(avg_vol, main_mode, int(cycles_24h), int(num_samples))
            _render_price_box(pricing)
        else:
            pricing = {}
    except Exception as e:
        st.error(f"Pricing error: {e}")
        pricing = {}

    ethical = _ethical_declaration("EGTP-Lyoph")

    return {
        "service_code":     "EGTP-Lyoph",
        "service_id":       "svc-egtp-lyoph",
        "requester":        requester,
        "analysis_info":    analysis,
        "biosafety":        biosafety,
        "samples":          samples,
        "cycles_24h":       int(cycles_24h),
        "pricing":          pricing,
        "ethical_signed":   ethical,
        "estimated_budget": pricing.get("total_dzd", 0.0),
    }


# ── EGTP-WGS Form ─────────────────────────────────────────────────────────────
def form_egtp_wgs(user: dict) -> dict:
    st.markdown("## 🔬 EGTP-Illumina-Microbial-WGS — Whole Genome Sequencing")
    st.info("Illumina MiSeq · From 85,000 DZD · 15–30 working days")

    requester = _requester_section(user)
    analysis  = _analysis_section()
    biosafety = _biosafety_section("wgs")

    st.markdown("### 🧪 Section 3 — Isolate Information")
    st.warning(
        "Required: Pure fresh colonies on suitable agar + "
        "4 sterile tubes × 5 mL liquid medium per isolate.")

    samples = []
    num_samples = st.number_input(
        "Number of isolates *", min_value=1, max_value=10, value=1, key="wgs_n")
    for i in range(int(num_samples)):
        with st.expander(f"Isolate #{i+1}", expanded=(i == 0)):
            c1, c2 = st.columns(2)
            with c1:
                code = st.text_input(
                    f"Isolate code * #{i+1}", key=f"wgs_code_{i}")
                org_type = st.selectbox(
                    f"Organism type * #{i+1}",
                    ["Bacterium", "Fungi", "Other"],
                    key=f"wgs_org_{i}")
                source = st.text_input(
                    f"Source / origin * #{i+1}", key=f"wgs_src_{i}")
            with c2:
                tubes_provided = st.checkbox(
                    f"4 × 5 mL sterile liquid medium tubes provided * #{i+1}",
                    key=f"wgs_tubes_{i}")
                if not tubes_provided:
                    st.error(
                        "4 sterile tubes × 5 mL liquid medium are mandatory "
                        "for DNA extraction regrowth.")
                label_confirmed = st.checkbox(
                    f"Isolate clearly labelled (code, source, type) * #{i+1}",
                    key=f"wgs_label_{i}")
            remarks = st.text_input(f"Remarks #{i+1}", key=f"wgs_rem_{i}")
            samples.append({
                "code": code, "organism_type": org_type, "source": source,
                "tubes_provided": tubes_provided,
                "label_confirmed": label_confirmed, "remarks": remarks,
            })

    st.markdown("### ⚙️ Section 4 — Sequencing Parameters")
    c1, c2 = st.columns(2)
    with c1:
        org_complexity = st.selectbox(
            "Organism complexity *",
            ["standard", "complex"],
            format_func=lambda x: {
                "standard": "Standard bacterial WGS — 85,000 DZD",
                "complex":  "Complex / fungi / large genome — adjusted pricing"
            }[x],
            key="wgs_complexity")
        depth_goal = st.text_input(
            "Sequencing depth / coverage goal *",
            placeholder="e.g. 30×, 50×, coverage TBD",
            key="wgs_depth")
    with c2:
        bioinf_required = st.checkbox(
            "Bioinformatics analysis required (quoted separately)",
            key="wgs_bioinf")
        bioinf_type = []
        if bioinf_required:
            bioinf_type = st.multiselect(
                "Bioinformatics type required",
                ["Genome assembly", "Genome annotation",
                 "AMR analysis", "Comparative genomics",
                 "Phylogenetic analysis"],
                key="wgs_bioinf_type")
            st.info(
                "A separate quote will be generated for bioinformatics services.")

    try:
        pricing = calculate_wgs(org_complexity, bioinf_required)
        pricing["total_dzd"] = pricing["total_dzd"] * int(num_samples)
        pricing["num_samples"] = int(num_samples)
        _render_price_box(pricing)
    except Exception as e:
        st.error(f"Pricing error: {e}")
        pricing = {}

    ethical = _ethical_declaration("EGTP-Illumina-Microbial-WGS")

    return {
        "service_code":        "EGTP-Illumina-Microbial-WGS",
        "service_id":          "svc-egtp-wgs",
        "requester":           requester,
        "analysis_info":       analysis,
        "biosafety":           biosafety,
        "samples":             samples,
        "organism_complexity": org_complexity,
        "sequencing_depth":    depth_goal,
        "bioinf_required":     bioinf_required,
        "bioinf_type":         bioinf_type,
        "pricing":             pricing,
        "ethical_signed":      ethical,
        "estimated_budget":    pricing.get("total_dzd", 0.0),
    }


# ── Form dispatcher ──────────────────────────────────────────────────────────
FORM_REGISTRY = {
    "svc-egtp-imt":   form_egtp_imt,
    "svc-egtp-seq01": form_egtp_seq01,
    "svc-egtp-seq02": form_egtp_seq02,
    "svc-egtp-seqs":  form_egtp_seqs,
    "svc-egtp-pcr":   form_egtp_pcr,
    "svc-egtp-can":   form_egtp_can,
    "svc-egtp-gde":   form_egtp_gde,
    "svc-egtp-ps":    form_egtp_ps,
    "svc-egtp-lyoph": form_egtp_lyoph,
    "svc-egtp-wgs":   form_egtp_wgs,
}

def render_service_form(service_id: str, user: dict) -> dict:
    """Dispatch to the correct service form by ID."""
    fn = FORM_REGISTRY.get(service_id)
    if not fn:
        st.error(f"No form registered for service: {service_id}")
        return {}
    return fn(user)