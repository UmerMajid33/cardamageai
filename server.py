"""Local web app: photograph damage, get an assessment and an estimate.

    python server.py   ->  http://127.0.0.1:5056
"""

import os

from flask import Flask, jsonify, request, send_from_directory

import assess
import db
import limits
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
    except limits.RateLimited as exc:
        return jsonify({"error": str(exc), "rate_limited": True}), 429
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

    # Gate before anything expensive happens. Cheap rejections must not consume
    # quota, and a wrong access code must not count against a rate limit.
    try:
        limits.check_access(request.headers.get("X-Access-Code", ""))
    except limits.AccessDenied as exc:
        return jsonify({"error": str(exc), "code_required": True}), 401

    def handler(conn):
        if not data_url.startswith("data:image/"):
            raise RuntimeError("No image received.")
        if len(data_url) > MAX_IMAGE_CHARS:
            raise RuntimeError(
                "That image is too large even after downscaling. Try a photo "
                "taken further back, or a lower camera resolution."
            )

        # Counted only once the request is worth spending quota on, so a
        # malformed upload never burns someone's allowance.
        limits.check_rate(limits.client_ip(request))

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


@app.get("/api/config")
def get_config():
    """What the page needs to know before it asks for anything."""
    return jsonify(limits.status())


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True})


if __name__ == "__main__":
    # Render supplies PORT; DAMAGESCAN_PORT is the local override.
    port = int(os.environ.get("PORT") or os.environ.get("DAMAGESCAN_PORT", "5056"))
    print(f"\n  Damage assessment  ->  http://127.0.0.1:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
