import json

from zpa.runio import CsvWriter, RunManifest


def test_manifest_refreshes_output_size_after_buffered_writer_closes(tmp_path):
    output = tmp_path / "findings.csv"

    with RunManifest("audit", tmp_path, argv=["audit"]) as manifest, \
            CsvWriter(output, ["code", "detail"]) as writer:
        writer.write({"code": "EXAMPLE", "detail": "buffered row"})
        manifest.add_output(output, "findings")

        # The row can still be buffered when the output is registered.
        assert manifest.data["outputs"][0]["bytes"] <= output.stat().st_size

    saved = json.loads((tmp_path / "audit.manifest.json").read_text())
    assert saved["outputs"] == [{
        "path": str(output),
        "exists": True,
        "bytes": output.stat().st_size,
        "desc": "findings",
    }]
