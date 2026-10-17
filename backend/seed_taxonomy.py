"""
================================================================================
MedLearn AI - Medical Knowledge Service: comprehensive taxonomy seed
================================================================================
Populates topic_taxonomy with 60+ medically accurate topics covering the major
organ systems, disease categories, and biological processes that a medical
education platform needs to support.

Idempotent - safe to run multiple times (skips entries that already exist
by canonical_name).

Usage:
    python seed_taxonomy.py

================================================================================
"""

import logging

from main import Base, SessionLocal, TopicTaxonomy, engine

logger = logging.getLogger("medlearn.seed_taxonomy")
logging.basicConfig(level=logging.INFO)

STARTER_TOPICS = [
    # ── Cardiovascular ────────────────────────────────────────────────────────
    {
        "canonical_name": "Coronary Artery Disease",
        "category": "cardiovascular",
        "synonyms": ["CAD", "ischemic heart disease", "atherosclerotic heart disease"],
        "related_topics": ["Heart Attack", "Hypertension", "Diabetes", "Cholesterol"],
    },
    {
        "canonical_name": "Heart Attack",
        "category": "cardiovascular",
        "synonyms": ["myocardial infarction", "MI", "acute coronary syndrome"],
        "related_topics": ["Coronary Artery Disease", "Hypertension", "Heart Failure"],
    },
    {
        "canonical_name": "Hypertension",
        "category": "cardiovascular",
        "synonyms": ["high blood pressure", "arterial hypertension"],
        "related_topics": ["Coronary Artery Disease", "Stroke", "Kidney Disease", "Diabetes"],
    },
    {
        "canonical_name": "Heart Failure",
        "category": "cardiovascular",
        "synonyms": ["congestive heart failure", "CHF", "cardiac failure"],
        "related_topics": ["Coronary Artery Disease", "Hypertension", "Atrial Fibrillation"],
    },
    {
        "canonical_name": "Atrial Fibrillation",
        "category": "cardiovascular",
        "synonyms": ["AFib", "AF", "irregular heartbeat"],
        "related_topics": ["Heart Failure", "Stroke", "Hypertension"],
    },
    {
        "canonical_name": "Deep Vein Thrombosis",
        "category": "cardiovascular",
        "synonyms": ["DVT", "blood clot in leg", "venous thromboembolism"],
        "related_topics": ["Pulmonary Embolism", "Atrial Fibrillation"],
    },
    {
        "canonical_name": "Cholesterol",
        "category": "cardiovascular",
        "synonyms": ["hypercholesterolemia", "dyslipidemia", "high cholesterol"],
        "related_topics": ["Coronary Artery Disease", "Diabetes", "Obesity"],
    },

    # ── Respiratory ───────────────────────────────────────────────────────────
    {
        "canonical_name": "Asthma",
        "category": "respiratory",
        "synonyms": ["reactive airway disease", "bronchial asthma"],
        "related_topics": ["Allergies", "COPD", "Influenza"],
    },
    {
        "canonical_name": "COPD",
        "category": "respiratory",
        "synonyms": ["chronic obstructive pulmonary disease", "emphysema", "chronic bronchitis"],
        "related_topics": ["Asthma", "Lung Cancer", "Influenza"],
    },
    {
        "canonical_name": "Pneumonia",
        "category": "respiratory",
        "synonyms": ["lung infection", "community-acquired pneumonia"],
        "related_topics": ["Influenza", "COVID-19", "Asthma", "COPD"],
    },
    {
        "canonical_name": "COVID-19",
        "category": "respiratory",
        "synonyms": ["SARS-CoV-2", "coronavirus disease 2019", "coronavirus"],
        "related_topics": ["Pneumonia", "Influenza", "Asthma"],
    },
    {
        "canonical_name": "Influenza",
        "category": "respiratory",
        "synonyms": ["flu", "seasonal flu", "influenza virus"],
        "related_topics": ["Pneumonia", "Asthma", "COVID-19"],
    },
    {
        "canonical_name": "Pulmonary Embolism",
        "category": "respiratory",
        "synonyms": ["PE", "blood clot in lungs"],
        "related_topics": ["Deep Vein Thrombosis", "Atrial Fibrillation"],
    },
    {
        "canonical_name": "Lung Cancer",
        "category": "respiratory",
        "synonyms": ["pulmonary carcinoma", "non-small cell lung cancer", "NSCLC"],
        "related_topics": ["COPD", "Asthma"],
    },

    # ── Endocrine ─────────────────────────────────────────────────────────────
    {
        "canonical_name": "Type 2 Diabetes Mellitus",
        "category": "endocrine",
        "synonyms": ["diabetes", "T2DM", "type 2 diabetes", "adult-onset diabetes"],
        "related_topics": ["Obesity", "Hypertension", "Coronary Artery Disease", "Kidney Disease"],
    },
    {
        "canonical_name": "Type 1 Diabetes Mellitus",
        "category": "endocrine",
        "synonyms": ["T1DM", "type 1 diabetes", "juvenile diabetes", "insulin-dependent diabetes"],
        "related_topics": ["Type 2 Diabetes Mellitus", "Kidney Disease"],
    },
    {
        "canonical_name": "Hypothyroidism",
        "category": "endocrine",
        "synonyms": ["underactive thyroid", "thyroid deficiency"],
        "related_topics": ["Obesity", "Hyperthyroidism"],
    },
    {
        "canonical_name": "Hyperthyroidism",
        "category": "endocrine",
        "synonyms": ["overactive thyroid", "Graves disease", "thyrotoxicosis"],
        "related_topics": ["Hypothyroidism", "Atrial Fibrillation"],
    },
    {
        "canonical_name": "Obesity",
        "category": "endocrine",
        "synonyms": ["overweight", "adiposity", "morbid obesity"],
        "related_topics": ["Type 2 Diabetes Mellitus", "Hypertension", "Heart Disease", "Sleep Apnea"],
    },
    {
        "canonical_name": "Cushing Syndrome",
        "category": "endocrine",
        "synonyms": ["hypercortisolism", "Cushing's disease"],
        "related_topics": ["Obesity", "Hypertension", "Type 2 Diabetes Mellitus"],
    },

    # ── Neurological ──────────────────────────────────────────────────────────
    {
        "canonical_name": "Stroke",
        "category": "neurological",
        "synonyms": ["cerebrovascular accident", "CVA", "brain attack", "ischemic stroke"],
        "related_topics": ["Hypertension", "Atrial Fibrillation", "Coronary Artery Disease"],
    },
    {
        "canonical_name": "Alzheimer's Disease",
        "category": "neurological",
        "synonyms": ["Alzheimer's", "dementia", "senile dementia", "AD"],
        "related_topics": ["Parkinson's Disease", "Stroke"],
    },
    {
        "canonical_name": "Parkinson's Disease",
        "category": "neurological",
        "synonyms": ["Parkinson's", "PD", "parkinsonian syndrome"],
        "related_topics": ["Alzheimer's Disease"],
    },
    {
        "canonical_name": "Epilepsy",
        "category": "neurological",
        "synonyms": ["seizure disorder", "convulsions"],
        "related_topics": ["Stroke", "Brain Tumor"],
    },
    {
        "canonical_name": "Migraine",
        "category": "neurological",
        "synonyms": ["chronic migraine", "migraine headache", "tension headache"],
        "related_topics": ["Stroke"],
    },
    {
        "canonical_name": "Multiple Sclerosis",
        "category": "neurological",
        "synonyms": ["MS", "demyelinating disease"],
        "related_topics": ["Epilepsy"],
    },
    {
        "canonical_name": "Meningitis",
        "category": "neurological",
        "synonyms": ["bacterial meningitis", "viral meningitis", "spinal meningitis"],
        "related_topics": ["Encephalitis", "Pneumonia"],
    },

    # ── Gastrointestinal ──────────────────────────────────────────────────────
    {
        "canonical_name": "Gastroesophageal Reflux Disease",
        "category": "gastrointestinal",
        "synonyms": ["GERD", "acid reflux", "heartburn", "acid indigestion"],
        "related_topics": ["Peptic Ulcer Disease", "Esophageal Cancer"],
    },
    {
        "canonical_name": "Peptic Ulcer Disease",
        "category": "gastrointestinal",
        "synonyms": ["stomach ulcer", "gastric ulcer", "duodenal ulcer", "peptic ulcer"],
        "related_topics": ["GERD", "H. pylori infection", "Gastric Cancer"],
    },
    {
        "canonical_name": "Irritable Bowel Syndrome",
        "category": "gastrointestinal",
        "synonyms": ["IBS", "spastic colon", "functional bowel disorder"],
        "related_topics": ["Crohn's Disease", "Ulcerative Colitis"],
    },
    {
        "canonical_name": "Crohn's Disease",
        "category": "gastrointestinal",
        "synonyms": ["Crohn disease", "inflammatory bowel disease", "regional enteritis"],
        "related_topics": ["Ulcerative Colitis", "IBS"],
    },
    {
        "canonical_name": "Ulcerative Colitis",
        "category": "gastrointestinal",
        "synonyms": ["UC", "inflammatory bowel disease", "colitis"],
        "related_topics": ["Crohn's Disease", "Colorectal Cancer"],
    },
    {
        "canonical_name": "Liver Cirrhosis",
        "category": "gastrointestinal",
        "synonyms": ["cirrhosis", "end-stage liver disease", "hepatic cirrhosis"],
        "related_topics": ["Hepatitis B", "Hepatitis C", "Liver Cancer"],
    },
    {
        "canonical_name": "Hepatitis B",
        "category": "gastrointestinal",
        "synonyms": ["HBV", "hepatitis B virus"],
        "related_topics": ["Liver Cirrhosis", "Hepatitis C", "Liver Cancer"],
    },
    {
        "canonical_name": "Hepatitis C",
        "category": "gastrointestinal",
        "synonyms": ["HCV", "hepatitis C virus"],
        "related_topics": ["Liver Cirrhosis", "Hepatitis B", "Liver Cancer"],
    },

    # ── Renal ─────────────────────────────────────────────────────────────────
    {
        "canonical_name": "Chronic Kidney Disease",
        "category": "renal",
        "synonyms": ["CKD", "chronic renal failure", "kidney failure", "renal insufficiency"],
        "related_topics": ["Diabetes", "Hypertension", "Kidney Stones"],
    },
    {
        "canonical_name": "Kidney Stones",
        "category": "renal",
        "synonyms": ["nephrolithiasis", "renal calculi", "urolithiasis"],
        "related_topics": ["Chronic Kidney Disease", "Urinary Tract Infection"],
    },
    {
        "canonical_name": "Urinary Tract Infection",
        "category": "renal",
        "synonyms": ["UTI", "bladder infection", "cystitis"],
        "related_topics": ["Kidney Stones", "Chronic Kidney Disease"],
    },

    # ── Musculoskeletal ───────────────────────────────────────────────────────
    {
        "canonical_name": "Osteoarthritis",
        "category": "musculoskeletal",
        "synonyms": ["OA", "degenerative joint disease", "wear-and-tear arthritis"],
        "related_topics": ["Rheumatoid Arthritis", "Gout", "Obesity"],
    },
    {
        "canonical_name": "Rheumatoid Arthritis",
        "category": "musculoskeletal",
        "synonyms": ["RA", "autoimmune arthritis"],
        "related_topics": ["Osteoarthritis", "Lupus"],
    },
    {
        "canonical_name": "Osteoporosis",
        "category": "musculoskeletal",
        "synonyms": ["bone loss", "brittle bone disease", "low bone density"],
        "related_topics": ["Hypothyroidism", "Cushing Syndrome"],
    },
    {
        "canonical_name": "Gout",
        "category": "musculoskeletal",
        "synonyms": ["hyperuricemia", "gouty arthritis"],
        "related_topics": ["Osteoarthritis", "Kidney Stones", "Hypertension"],
    },

    # ── Oncology ──────────────────────────────────────────────────────────────
    {
        "canonical_name": "Breast Cancer",
        "category": "oncology",
        "synonyms": ["mammary carcinoma", "BRCA"],
        "related_topics": ["Cervical Cancer", "Ovarian Cancer"],
    },
    {
        "canonical_name": "Colorectal Cancer",
        "category": "oncology",
        "synonyms": ["colon cancer", "rectal cancer", "CRC"],
        "related_topics": ["Ulcerative Colitis", "Crohn's Disease"],
    },
    {
        "canonical_name": "Prostate Cancer",
        "category": "oncology",
        "synonyms": ["prostate carcinoma", "PCa"],
        "related_topics": ["Bladder Cancer"],
    },
    {
        "canonical_name": "Leukemia",
        "category": "oncology",
        "synonyms": ["blood cancer", "ALL", "AML", "CLL", "CML"],
        "related_topics": ["Lymphoma"],
    },
    {
        "canonical_name": "Lymphoma",
        "category": "oncology",
        "synonyms": ["Hodgkin lymphoma", "non-Hodgkin lymphoma", "NHL"],
        "related_topics": ["Leukemia"],
    },

    # ── Infectious Disease ────────────────────────────────────────────────────
    {
        "canonical_name": "HIV/AIDS",
        "category": "infectious_disease",
        "synonyms": ["human immunodeficiency virus", "AIDS", "HIV infection"],
        "related_topics": ["Tuberculosis", "Hepatitis B", "Hepatitis C"],
    },
    {
        "canonical_name": "Tuberculosis",
        "category": "infectious_disease",
        "synonyms": ["TB", "Mycobacterium tuberculosis", "pulmonary tuberculosis"],
        "related_topics": ["HIV/AIDS", "Pneumonia"],
    },
    {
        "canonical_name": "Malaria",
        "category": "infectious_disease",
        "synonyms": ["Plasmodium infection", "falciparum malaria"],
        "related_topics": ["Dengue Fever", "Tuberculosis"],
    },
    {
        "canonical_name": "Sepsis",
        "category": "infectious_disease",
        "synonyms": ["blood poisoning", "systemic infection", "septicemia"],
        "related_topics": ["Pneumonia", "Urinary Tract Infection"],
    },

    # ── Immunological ─────────────────────────────────────────────────────────
    {
        "canonical_name": "Allergies",
        "category": "immunological",
        "synonyms": ["allergic reaction", "hypersensitivity", "atopy"],
        "related_topics": ["Asthma", "Anaphylaxis"],
    },
    {
        "canonical_name": "Lupus",
        "category": "immunological",
        "synonyms": ["systemic lupus erythematosus", "SLE", "lupus erythematosus"],
        "related_topics": ["Rheumatoid Arthritis", "Kidney Disease"],
    },
    {
        "canonical_name": "Anaphylaxis",
        "category": "immunological",
        "synonyms": ["anaphylactic shock", "severe allergic reaction"],
        "related_topics": ["Allergies", "Asthma"],
    },

    # ── Dermatological ────────────────────────────────────────────────────────
    {
        "canonical_name": "Psoriasis",
        "category": "dermatological",
        "synonyms": ["plaque psoriasis", "psoriatic disease"],
        "related_topics": ["Rheumatoid Arthritis", "Lupus"],
    },
    {
        "canonical_name": "Eczema",
        "category": "dermatological",
        "synonyms": ["atopic dermatitis", "atopic eczema"],
        "related_topics": ["Allergies", "Asthma", "Psoriasis"],
    },
    {
        "canonical_name": "Skin Cancer",
        "category": "dermatological",
        "synonyms": ["melanoma", "basal cell carcinoma", "squamous cell carcinoma"],
        "related_topics": ["Breast Cancer", "Lung Cancer"],
    },

    # ── Mental Health ─────────────────────────────────────────────────────────
    {
        "canonical_name": "Depression",
        "category": "mental_health",
        "synonyms": ["major depressive disorder", "MDD", "clinical depression"],
        "related_topics": ["Anxiety", "Bipolar Disorder"],
    },
    {
        "canonical_name": "Anxiety",
        "category": "mental_health",
        "synonyms": ["generalized anxiety disorder", "GAD", "anxiety disorder"],
        "related_topics": ["Depression", "PTSD"],
    },
    {
        "canonical_name": "Schizophrenia",
        "category": "mental_health",
        "synonyms": ["psychosis", "schizoaffective disorder"],
        "related_topics": ["Bipolar Disorder", "Depression"],
    },

    # ── Anatomy / Physiology ──────────────────────────────────────────────────
    {
        "canonical_name": "Human Heart",
        "category": "anatomy",
        "synonyms": ["cardiac anatomy", "heart structure", "cardiac physiology"],
        "related_topics": ["Coronary Artery Disease", "Heart Failure", "Heart Attack"],
    },
    {
        "canonical_name": "Human Brain",
        "category": "anatomy",
        "synonyms": ["brain anatomy", "cerebral cortex", "neuroscience basics"],
        "related_topics": ["Stroke", "Alzheimer's Disease", "Epilepsy"],
    },
    {
        "canonical_name": "Human Immune System",
        "category": "anatomy",
        "synonyms": ["immunology", "immune response", "lymphatic system"],
        "related_topics": ["Allergies", "Lupus", "HIV/AIDS"],
    },
    {
        "canonical_name": "Human Kidney",
        "category": "anatomy",
        "synonyms": ["renal anatomy", "nephrology basics", "kidney function"],
        "related_topics": ["Chronic Kidney Disease", "Kidney Stones", "Diabetes"],
    },
    {
        "canonical_name": "Cell Biology",
        "category": "biology",
        "synonyms": ["cellular biology", "cytology", "cell structure"],
        "related_topics": ["DNA and Genetics", "Cancer Biology"],
    },
    {
        "canonical_name": "DNA and Genetics",
        "category": "biology",
        "synonyms": ["genomics", "heredity", "gene expression", "molecular biology"],
        "related_topics": ["Cell Biology", "Cancer Biology"],
    },
    {
        "canonical_name": "Inflammation",
        "category": "biology",
        "synonyms": ["inflammatory response", "acute inflammation", "chronic inflammation"],
        "related_topics": ["Allergies", "Rheumatoid Arthritis", "Crohn's Disease"],
    },
]


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    created = 0
    skipped = 0
    try:
        for topic in STARTER_TOPICS:
            existing = (
                db.query(TopicTaxonomy)
                .filter(TopicTaxonomy.canonical_name == topic["canonical_name"])
                .first()
            )
            if existing:
                logger.info("Skipping '%s' — already exists", topic["canonical_name"])
                skipped += 1
                continue
            db.add(TopicTaxonomy(**topic))
            db.commit()
            created += 1
            logger.info("Created: %s [%s]", topic["canonical_name"], topic["category"])
    finally:
        db.close()

    logger.info(
        "Seed complete: %d new entries created, %d already existed (total in seed list: %d)",
        created,
        skipped,
        len(STARTER_TOPICS),
    )


if __name__ == "__main__":
    main()
