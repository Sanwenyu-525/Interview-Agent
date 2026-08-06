import json
import unittest
from dataclasses import asdict, replace
from pathlib import Path

from interview_agent.analyzers.base import ArtifactAnalyzer
from interview_agent.intelligence.models import (
    Component,
    Evidence,
    Flow,
    Insight,
    ProjectIdentity,
    ProjectTopic,
    Relation,
    StructureNode,
    Technology,
    UniversalProjectModel,
    project_model_to_knowledge,
)
from interview_agent.models import project_model_to_knowledge as legacy_project_model_to_knowledge
from interview_agent.repository import InMemoryProjectRepository
from interview_agent.tools import ProjectTools


def sample_model():
    evidence = [
        Evidence(
            id="e-cache",
            source_path="src/CacheService.java",
            locator="CacheService.get",
            excerpt="return redisTemplate.opsForValue().get(key);",
            kind="code",
            confidence=0.73,
        )
    ]
    return UniversalProjectModel(
        project_id=7,
        identity=ProjectIdentity(
            name="Order System",
            artifact_type="java_backend",
            goal="Process orders",
            description="An order processing service.",
        ),
        structure=[StructureNode(id="src", name="src", kind="directory")],
        technologies=[Technology(name="Redis", category="cache", evidence_ids=["e-cache"])],
        components=[
            Component(
                id="cache-service",
                name="CacheService",
                kind="service",
                path="src/CacheService.java",
                evidence_ids=["e-cache"],
            )
        ],
        relations=[
            Relation(
                source_id="order-service",
                target_id="cache-service",
                kind="depends_on",
                evidence_ids=["e-cache"],
            )
        ],
        flows=[
            Flow(
                id="order-read",
                name="Read order",
                component_ids=["order-service", "cache-service"],
            )
        ],
        insights=[
            Insight(
                id="i-cache",
                kind="tradeoff",
                summary="Cache lookup reduces database load.",
                topic="Redis",
                score=85,
                evidence_ids=["e-cache"],
            )
        ],
        evidence=evidence,
        topics=[ProjectTopic(name="Redis", score=85, evidence_ids=["e-cache"])],
    )


class StubAnalyzer:
    analyzer_id = "stub"

    def supports(self, structure):
        return structure == "java_backend"

    def analyze(self, artifact_root: Path, project_id: int):
        return sample_model()


class IntelligenceModelTests(unittest.TestCase):
    def test_universal_model_dataclasses_are_json_serializable(self):
        model = sample_model()

        payload = json.loads(json.dumps(asdict(model), ensure_ascii=False))

        self.assertEqual(payload["identity"]["name"], "Order System")
        self.assertEqual(payload["evidence"][0]["confidence"], 0.73)
        self.assertEqual(payload["components"][0]["evidence_ids"], ["e-cache"])
        self.assertEqual(payload["relations"][0]["evidence_ids"], ["e-cache"])

    def test_project_model_converts_to_legacy_project_knowledge(self):
        knowledge = project_model_to_knowledge(sample_model())

        self.assertEqual(knowledge.project_id, 7)
        self.assertEqual(knowledge.project_name, "Order System")
        self.assertEqual(knowledge.topics[0].name, "Redis")
        self.assertEqual(knowledge.topics[0].evidence, ["e-cache"])
        self.assertEqual(knowledge.components["CacheService"], "src/CacheService.java")
        self.assertEqual(knowledge.evidence["e-cache"]["confidence"], 0.73)
        self.assertEqual(knowledge.dependencies, {"order-service": ["cache-service"]})

    def test_project_tools_can_find_converted_evidence_by_topic(self):
        knowledge = project_model_to_knowledge(sample_model())
        tools = ProjectTools(InMemoryProjectRepository({7: knowledge}))

        evidence = tools.get_evidence(7, "Redis")

        self.assertIsNotNone(evidence)
        self.assertEqual(evidence["source_path"], "src/CacheService.java")
        self.assertEqual(evidence, knowledge.evidence["e-cache"])

    def test_topic_alias_does_not_overwrite_same_named_evidence_id(self):
        model = replace(
            sample_model(),
            evidence=[
                Evidence(
                    id="Redis",
                    source_path="docs/redis.md",
                    locator="line 2",
                    excerpt="Redis is used for sessions.",
                    kind="text",
                    confidence=0.8,
                ),
                *sample_model().evidence,
            ],
        )

        knowledge = project_model_to_knowledge(model)
        tools = ProjectTools(InMemoryProjectRepository({7: knowledge}))

        self.assertEqual(knowledge.evidence["Redis"]["source_path"], "docs/redis.md")
        self.assertEqual(
            tools.get_evidence(7, "Redis")["source_path"],
            "src/CacheService.java",
        )
        self.assertEqual(knowledge.evidence["topic:Redis"], knowledge.evidence["e-cache"])

    def test_topic_with_multiple_evidence_ids_is_rejected_as_ambiguous(self):
        model = replace(
            sample_model(),
            evidence=[
                *sample_model().evidence,
                Evidence(
                    id="e-database",
                    source_path="src/OrderRepository.java",
                    locator="OrderRepository.find",
                    excerpt="return query;",
                    kind="code",
                    confidence=0.7,
                ),
            ],
            topics=[ProjectTopic(name="Redis", score=85, evidence_ids=["e-cache", "e-database"])],
        )

        with self.assertRaisesRegex(ValueError, "Redis.*evidence"):
            project_model_to_knowledge(model)

    def test_conflicting_topic_without_evidence_id_is_rejected(self):
        model = replace(
            sample_model(),
            evidence=[
                Evidence(
                    id="Redis",
                    source_path="docs/redis.md",
                    locator="line 2",
                    excerpt="Redis is used for sessions.",
                    kind="text",
                    confidence=0.8,
                ),
                *sample_model().evidence,
            ],
            topics=[ProjectTopic(name="Redis", score=85)],
        )

        with self.assertRaisesRegex(ValueError, "Redis.*evidence"):
            project_model_to_knowledge(model)

    def test_duplicate_evidence_ids_are_rejected_when_model_is_created(self):
        evidence = sample_model().evidence[0]

        with self.assertRaisesRegex(ValueError, "duplicate Evidence.id"):
            replace(sample_model(), evidence=[evidence, evidence])

    def test_duplicate_component_names_are_rejected_when_model_is_created(self):
        component = sample_model().components[0]

        with self.assertRaisesRegex(ValueError, "duplicate component name"):
            replace(sample_model(), components=[component, replace(component, id="cache-copy")])

    def test_mapping_evidence_is_rejected_at_model_boundary(self):
        with self.assertRaisesRegex(TypeError, r"evidence must be list\[Evidence\]"):
            UniversalProjectModel(
                project_id=8,
                identity=ProjectIdentity(name="Invalid evidence project"),
                evidence={
                    "mapped": {
                        "source_path": Path("docs/evidence.md"),
                        "metadata": {"tags": {"mapped", "safe"}},
                    }
                },
            )

    def test_evidence_metadata_is_json_safe_after_model_creation(self):
        evidence = Evidence(
            id="e-metadata",
            source_path="README.md",
            locator="line 1",
            excerpt="cache",
            kind="text",
            confidence=0.91,
            metadata={
                "path": Path("docs/README.md"),
                "tags": {"cache", "redis"},
                "nested": (Path("src"), {"count": 1}),
            },
        )
        model = UniversalProjectModel(
            project_id=8,
            identity=ProjectIdentity(name="Metadata project"),
            evidence=[evidence],
        )

        payload = json.loads(json.dumps(asdict(model), ensure_ascii=False))

        self.assertEqual(payload["evidence"][0]["metadata"]["path"], str(Path("docs/README.md")))
        self.assertEqual(set(payload["evidence"][0]["metadata"]["tags"]), {"cache", "redis"})
        self.assertEqual(payload["evidence"][0]["metadata"]["nested"][0], "src")

    def test_legacy_models_module_exposes_compatibility_conversion(self):
        knowledge = legacy_project_model_to_knowledge(sample_model())

        self.assertEqual(knowledge.project_id, 7)
        self.assertEqual(knowledge.project_name, "Order System")

    def test_artifact_analyzer_protocol_describes_analyzer_boundary(self):
        self.assertIsInstance(StubAnalyzer(), ArtifactAnalyzer)
        self.assertTrue(StubAnalyzer().supports("java_backend"))
        self.assertEqual(StubAnalyzer().analyze(Path("."), 7).project_id, 7)


if __name__ == "__main__":
    unittest.main()
