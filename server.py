"""Local web app: photograph damage, get an assessment and an estimate.

    python server.py   ->  http://127.0.0.1:5056
"""

import os

from flask import Flask, jsonify, request, send_from_directory

import assess
import db
import llm
import pricing

app = Flask(__name__, static_folder="static", static_url_path="")

# A downscaled 800px JPEG lands around 150KB; this leaves generous headroom
# while still refusing anything that would blow the token budget.
MAX_IMAGE_CHARS = 3_500_000


def api(handler):
    conn = db.connect()
    try:
        return jsonify(handler(conn))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    finally:
        conn.close()


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.post("/api/assess")
def post_assess():
    body = request.get_json(silent=True) or {}
    data_url = body.get("image", "")

    def handler(conn):
        if not data_url.startswith("data:image/"):
            raise RuntimeError("No image received.")
        if len(data_url) > MAX_IMAGE_CHARS:
            raise RuntimeError(
                "That image is too large even after downscaling. Try a photo "
                "taken further back, or a lower camera resolution."
            )

        report, usage = llm.analyse_image(
            data_url, assess.SYSTEM, assess.USER_PROMPT, assess.SCHEMA)

        # Guard rails the model is told about but may still get wrong: an empty
        # findings list must not produce a confident zero-cost estimate.
        if not report["is_vehicle"]:
            estimate = None
        else:
            estimate = pricing.estimate(report["findings"])

        reference = db.next_reference(conn)
        assessment_id = db.save(conn, reference, data_url, report,
                                estimate or {}, llm.MODEL, usage)

        return {
            "id": assessment_id,
            "reference": reference,
            "report": report,
            "estimate": estimate,
            "model": llm.MODEL,
            "usage": {"in": usage.input_tokens, "out": usage.output_tokens},
        }

    return api(handler)


@app.get("/api/history")
def get_history():
    return api(lambda conn: {"items": db.recent(conn)})


@app.get("/api/assessment/<int:assessment_id>")
def get_assessment(assessment_id):
    def handler(conn):
        item = db.get(conn, assessment_id)
        if item is None:
            raise RuntimeError("No such assessment.")
        return item

    return api(handler)


@app.get("/api/rates")
def get_rates():
    return api(lambda conn: pricing.load_rates())


if __name__ == "__main__":
    port = int(os.environ.get("DAMAGESCAN_PORT", "5056"))
    print(f"\n  Damage assessment  ->  http://127.0.0.1:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
