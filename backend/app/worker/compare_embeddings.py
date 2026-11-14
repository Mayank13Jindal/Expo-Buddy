import json

from app.core.config import Settings
from app.pipeline.embeddings import encode


def main():
    samples = [
        (
            "making solar structures",
            "Fictional Alpha manufactures solar panel mounting structures.",
        ),
        (
            "water filtration equipment",
            "Fictional Beta makes reverse osmosis membranes and water filters.",
        ),
        (
            "warehouse automation",
            "Fictional Gamma supplies conveyor systems and warehouse sorting robots.",
        ),
        ("packing food products", "Fictional Delta builds food packaging and sealing machines."),
        (
            "industrial power cables",
            "Fictional Epsilon manufactures electrical wires and industrial cables.",
        ),
        (
            "cold storage systems",
            "Fictional Zeta installs commercial refrigeration and cold rooms.",
        ),
    ]
    results = {}
    for name in ("minilm", "bge"):
        settings = Settings().model_copy(update={"embedding_model": name})
        passages = encode([text for _, text in samples], settings)
        queries = encode([query for query, _ in samples], settings, query=True)
        correct = sum(
            max(
                range(len(passages)),
                key=lambda j: sum(a * b for a, b in zip(vector, passages[j], strict=True)),
            )
            == i
            for i, vector in enumerate(queries)
        )
        results[name] = {"synthetic_top1": correct, "samples": len(samples)}
    print(
        json.dumps(
            {
                "results": results,
                "owner_samples_measured": False,
                "selection": "minilm (baseline; owner evaluation pending)",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
