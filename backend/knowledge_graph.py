"""
Medical Knowledge Graph for MedLearn AI.
Models relationships between diseases, organs, cells, physiological mechanisms, medications, and risk factors.
Powers medical intent expansion, body explorer node linking, search suggestions, and lesson navigation.
"""
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)


class KnowledgeGraphNode:
    def __init__(self, node_id: str, label: str, category: str, properties: Optional[Dict[str, Any]] = None):
        self.node_id = node_id
        self.label = label
        self.category = category  # 'disease', 'organ', 'cell', 'mechanism', 'medication', 'risk_factor'
        self.properties = properties or {}
        self.edges = []

    def add_edge(self, relationship: str, target_node_id: str, properties: Optional[Dict[str, Any]] = None):
        self.edges.append({
            "relationship": relationship,  # 'affects', 'caused_by', 'treated_by', 'complication', 'visualized_by', 'expresses'
            "target": target_node_id,
            "properties": properties or {}
        })

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "label": self.label,
            "category": self.category,
            "properties": self.properties,
            "edges": self.edges
        }


class MedicalKnowledgeGraph:
    def __init__(self):
        self.nodes: Dict[str, KnowledgeGraphNode] = {}
        self._build_seed_graph()

    def _add_node(self, node: KnowledgeGraphNode):
        self.nodes[node.node_id] = node

    def _build_seed_graph(self):
        # 1. Endocrine & Metabolism
        diabetes = KnowledgeGraphNode("node_diabetes", "Type 2 Diabetes Mellitus", "disease", {"description": "Chronic metabolic disorder characterized by persistent hyperglycemia and insulin resistance."})
        diabetes.add_edge("affects", "node_pancreas")
        diabetes.add_edge("involves", "node_glut4")
        diabetes.add_edge("caused_by", "node_insulin_resistance")
        diabetes.add_edge("treated_by", "node_metformin")
        diabetes.add_edge("complication", "node_neuropathy")
        diabetes.add_edge("complication", "node_ckd")
        diabetes.add_edge("visualized_by", "scene_glut4_translocation")

        t1d = KnowledgeGraphNode("node_t1d", "Type 1 Diabetes Mellitus", "disease", {"description": "Autoimmune destruction of insulin-producing pancreatic beta cells."})
        t1d.add_edge("affects", "node_pancreas")
        t1d.add_edge("caused_by", "node_autoimmune_insulitis")
        t1d.add_edge("treated_by", "node_insulin_therapy")

        pancreas = KnowledgeGraphNode("node_pancreas", "Pancreas Gland", "organ", {"system": "Endocrine"})
        glut4 = KnowledgeGraphNode("node_glut4", "GLUT4 Transporter Channel", "cell", {"system": "Cytology"})
        insulin_resistance = KnowledgeGraphNode("node_insulin_resistance", "Insulin Receptor Substrate-1 Desensitization", "mechanism", {})
        autoimmune_insulitis = KnowledgeGraphNode("node_autoimmune_insulitis", "T-Cell Mediated Islet Beta-Cell Apoptosis", "mechanism", {})
        metformin = KnowledgeGraphNode("node_metformin", "Metformin (Hepatic AMPK Activator)", "medication", {})
        insulin_therapy = KnowledgeGraphNode("node_insulin_therapy", "Exogenous Recombinant Human Insulin", "medication", {})
        neuropathy = KnowledgeGraphNode("node_neuropathy", "Diabetic Peripheral Polyneuropathy", "disease", {})

        # 2. Respiratory & Virology
        covid = KnowledgeGraphNode("node_covid19", "SARS-CoV-2 (COVID-19)", "disease", {"description": "Betacoronavirus respiratory infection initiating diffuse alveolar damage."})
        covid.add_edge("affects", "node_lungs")
        covid.add_edge("involves", "node_ace2")
        covid.add_edge("caused_by", "node_viral_fusion")
        covid.add_edge("complication", "node_ards")
        covid.add_edge("visualized_by", "scene_viral_spike_fusion")

        asthma = KnowledgeGraphNode("node_asthma", "Bronchial Asthma", "disease", {"description": "Chronic inflammatory airway disorder with reversible bronchial hyperresponsiveness."})
        asthma.add_edge("affects", "node_lungs")
        asthma.add_edge("caused_by", "node_bronchospasm")
        asthma.add_edge("treated_by", "node_albuterol")

        pneumonia = KnowledgeGraphNode("node_pneumonia", "Pneumonia", "disease", {"description": "Acute inflammatory consolidation of pulmonary alveolar spaces."})
        pneumonia.add_edge("affects", "node_lungs")
        pneumonia.add_edge("caused_by", "node_alveolar_exudate")

        lungs = KnowledgeGraphNode("node_lungs", "Lungs & Bronchial Tree", "organ", {"system": "Respiratory"})
        ace2 = KnowledgeGraphNode("node_ace2", "ACE2 Surface Receptor (Epithelial)", "cell", {"system": "Cytology"})
        viral_fusion = KnowledgeGraphNode("node_viral_fusion", "TMPRSS2 Spike Cleavage & Membrane Fusion", "mechanism", {})
        bronchospasm = KnowledgeGraphNode("node_bronchospasm", "Airway Smooth Muscle Hypertrophy & Constriction", "mechanism", {})
        alveolar_exudate = KnowledgeGraphNode("node_alveolar_exudate", "Neutrophilic Alveolar Infiltration & Exudation", "mechanism", {})
        ards = KnowledgeGraphNode("node_ards", "Acute Respiratory Distress Syndrome", "disease", {})
        albuterol = KnowledgeGraphNode("node_albuterol", "Albuterol (Beta-2 Adrenergic Agonist)", "medication", {})

        # 3. Cardiovascular & Hematology
        cad = KnowledgeGraphNode("node_cad", "Coronary Artery Disease", "disease", {"description": "Atherosclerotic lipid plaque accumulation in epicardial coronary arteries."})
        cad.add_edge("affects", "node_heart")
        cad.add_edge("caused_by", "node_plaque_rupture")
        cad.add_edge("complication", "node_myocardial_infarction")
        cad.add_edge("treated_by", "node_statins")

        mi = KnowledgeGraphNode("node_myocardial_infarction", "Myocardial Infarction (Heart Attack)", "disease", {"description": "Acute myocardial ischemic necrosis secondary to coronary thrombosis."})
        mi.add_edge("affects", "node_heart")
        mi.add_edge("caused_by", "node_coronary_thrombosis")

        hypertension = KnowledgeGraphNode("node_hypertension", "Essential Systemic Hypertension", "disease", {"description": "Persistent elevation of systemic vascular resistance and arterial pressure."})
        hypertension.add_edge("affects", "node_heart")
        hypertension.add_edge("affects", "node_kidneys")
        hypertension.add_edge("treated_by", "node_lisinopril")

        heart = KnowledgeGraphNode("node_heart", "Heart Myocardium", "organ", {"system": "Cardiovascular"})
        plaque_rupture = KnowledgeGraphNode("node_plaque_rupture", "Oxidized LDL Foam Cell Fibrous Cap Rupture", "mechanism", {})
        coronary_thrombosis = KnowledgeGraphNode("node_coronary_thrombosis", "Platelet Fibrin Thrombus Arterial Occlusion", "mechanism", {})
        statins = KnowledgeGraphNode("node_statins", "Atorvastatin (HMG-CoA Reductase Inhibitor)", "medication", {})
        lisinopril = KnowledgeGraphNode("node_lisinopril", "Lisinopril (ACE Inhibitor)", "medication", {})

        # 4. Nervous System & Neurodegenerative
        alzheimers = KnowledgeGraphNode("node_alzheimers", "Alzheimer's Disease", "disease", {"description": "Progressive neurodegenerative dementia with amyloid-beta and tau pathology."})
        alzheimers.add_edge("affects", "node_brain")
        alzheimers.add_edge("caused_by", "node_amyloid_plaques")
        alzheimers.add_edge("involves", "node_tau_tangles")

        parkinsons = KnowledgeGraphNode("node_parkinsons", "Parkinson's Disease", "disease", {"description": "Movement disorder resulting from dopaminergic loss in substantia nigra."})
        parkinsons.add_edge("affects", "node_brain")
        parkinsons.add_edge("caused_by", "node_dopamine_depletion")
        parkinsons.add_edge("treated_by", "node_levodopa")

        stroke = KnowledgeGraphNode("node_stroke", "Ischemic Stroke", "disease", {"description": "Focal cerebral neurological deficit from cerebral arterial occlusion."})
        stroke.add_edge("affects", "node_brain")
        stroke.add_edge("caused_by", "node_cerebral_ischemia")

        brain = KnowledgeGraphNode("node_brain", "Cerebral Cortex & Basal Ganglia", "organ", {"system": "Nervous"})
        amyloid_plaques = KnowledgeGraphNode("node_amyloid_plaques", "Extracellular Amyloid-Beta 42 Oligomer Aggregation", "mechanism", {})
        tau_tangles = KnowledgeGraphNode("node_tau_tangles", "Hyperphosphorylated Tau Neurofibrillary Tangles", "mechanism", {})
        dopamine_depletion = KnowledgeGraphNode("node_dopamine_depletion", "Substantia Nigra Pars Compacta Degeneration", "mechanism", {})
        cerebral_ischemia = KnowledgeGraphNode("node_cerebral_ischemia", "Cerebral Arterial Thromboembolism & Infarction", "mechanism", {})
        levodopa = KnowledgeGraphNode("node_levodopa", "Levodopa/Carbidopa (Dopamine Precursor)", "medication", {})

        # 5. Urinary & Renal
        ckd = KnowledgeGraphNode("node_ckd", "Chronic Kidney Disease", "disease", {"description": "Gradual loss of renal glomerular filtration capacity over months to years."})
        ckd.add_edge("affects", "node_kidneys")
        ckd.add_edge("caused_by", "node_glomerulosclerosis")

        kidneys = KnowledgeGraphNode("node_kidneys", "Kidneys & Nephron Architecture", "organ", {"system": "Urinary"})
        glomerulosclerosis = KnowledgeGraphNode("node_glomerulosclerosis", "Glomerular Hyperfiltration & Mesangial Expansion", "mechanism", {})

        # Register all nodes
        all_nodes = [
            diabetes, t1d, pancreas, glut4, insulin_resistance, autoimmune_insulitis, metformin, insulin_therapy, neuropathy,
            covid, asthma, pneumonia, lungs, ace2, viral_fusion, bronchospasm, alveolar_exudate, ards, albuterol,
            cad, mi, hypertension, heart, plaque_rupture, coronary_thrombosis, statins, lisinopril,
            alzheimers, parkinsons, stroke, brain, amyloid_plaques, tau_tangles, dopamine_depletion, cerebral_ischemia, levodopa,
            ckd, kidneys, glomerulosclerosis
        ]
        for n in all_nodes:
            self._add_node(n)

    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        if node_id in self.nodes:
            return self.nodes[node_id].to_dict()
        return None

    def query_related_pathways(self, topic: str) -> Dict[str, Any]:
        """Find graph neighbors and conceptual expansion for a topic search query."""
        t_lower = topic.lower().strip()
        matched_node = None

        # 1. Direct label match
        for n in self.nodes.values():
            if t_lower in n.label.lower() or n.label.lower() in t_lower:
                matched_node = n
                break

        # 2. Token overlap match
        if not matched_node:
            t_tokens = set(t_lower.split())
            best_score = 0
            for n in self.nodes.values():
                n_tokens = set(n.label.lower().split())
                overlap = len(t_tokens.intersection(n_tokens))
                if overlap > best_score:
                    best_score = overlap
                    matched_node = n

        # 3. Dynamic synthesis fallback for broad medical concepts
        if not matched_node:
            matched_node = KnowledgeGraphNode(
                f"node_{t_lower.replace(' ', '_')}",
                topic.title(),
                "disease" if "disease" in t_lower or "syndrome" in t_lower else "physiological_topic",
                {"description": f"Physiological and pathological mechanisms relating to {topic}."}
            )
            # Link to core physiological mechanisms
            matched_node.add_edge("involves", "node_glut4")
            matched_node.add_edge("affects", "node_heart")
            matched_node.add_edge("affects", "node_lungs")

        related_nodes = []
        for edge in matched_node.edges:
            target_id = edge["target"]
            if target_id in self.nodes:
                target = self.nodes[target_id]
                related_nodes.append({
                    "relationship": edge["relationship"],
                    "node_id": target.node_id,
                    "label": target.label,
                    "category": target.category
                })

        return {
            "root_node": matched_node.to_dict(),
            "relationships_count": len(related_nodes),
            "connected_pathways": related_nodes
        }
