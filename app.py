from flask import Flask, render_template, request, jsonify, redirect, send_file
import time
from datetime import datetime
import json
import os
import pandas as pd
import io

app = Flask(__name__)

# ---------------- Data -------------------
DATA_FILE = "data.json"

# Load or initialize data
if os.path.exists(DATA_FILE) and os.path.getsize(DATA_FILE) > 0:
    with open(DATA_FILE, "r") as f:
        try:
            data = json.load(f)
            production_data = data.get("production_data", {
                "current_item": "",
                "time_in_sec": 0,
                "count": 0,
                "start_time": None,
                "running": False,
                "target_count": 0,
                "items_queue": []
            })
            report_history = data.get("report_history", [])
        except json.JSONDecodeError:
            production_data = {
                "current_item": "",
                "time_in_sec": 0,
                "count": 0,
                "start_time": None,
                "running": False,
                "target_count": 0,
                "items_queue": []
            }
            report_history = []
else:
    production_data = {
        "current_item": "",
        "time_in_sec": 0,
        "count": 0,
        "start_time": None,
        "running": False,
        "target_count": 0,
        "items_queue": []
    }
    report_history = []

# Shift timings (decimal hours)
shifts = {
    "A": (0.5, 7.5),     # 12:30 AM - 7:30 AM
    "B": (7.33, 16),     # 7:20 AM - 4:00 PM
    "C": (16, 24.5)      # 4:00 PM - 12:30 AM
}

# ---------------- Helper -------------------
def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump({
            "production_data": production_data,
            "report_history": report_history
        }, f, indent=4)

# ---------------- ROUTES -------------------

# Dashboard
@app.route("/")
def dashboard():
    # Calculate shift-wise totals
    shift_totals = {"A": {"count": 0, "time": 0},
                    "B": {"count": 0, "time": 0},
                    "C": {"count": 0, "time": 0}}

    for r in report_history:
        shift = r.get("shift", "C")
        shift_totals[shift]["count"] += r.get("count", 0)
        shift_totals[shift]["time"] += r.get("total_seconds", 0)

    return render_template("dashboard.html", 
                           data=production_data,
                           shift_totals=shift_totals)


# Settings page
@app.route("/settings")
def settings():
    return render_template("settings.html", production_data=production_data)

# Add new item
@app.route("/save_settings", methods=["POST"])
def save_settings():
    item = request.form["item"]
    seconds = int(request.form["seconds"])
    total_count = int(request.form["total_count"])
    shift = request.form.get("shift", "A")

    production_data["items_queue"].append({
        "item": item,
        "seconds": seconds,
        "target_count": total_count,
        "shift": shift
    })

    # If no current item, set first item
    if not production_data["current_item"]:
        first = production_data["items_queue"][0]
        production_data["current_item"] = first["item"]
        production_data["time_in_sec"] = first["seconds"]
        production_data["target_count"] = first["target_count"]
        production_data["count"] = 0

    save_data()
    return redirect("/settings")

# Start production
@app.route("/start", methods=["POST"])
def start():
    if not production_data["running"] and production_data["current_item"]:
        production_data["start_time"] = time.time()
        production_data["running"] = True
        save_data()
    return jsonify({"status": "started"})

# Stop production
@app.route("/stop", methods=["POST"])
def stop():
    production_data["running"] = False
    save_data()
    return jsonify({"status": "stopped"})

# Update live dashboard
@app.route("/update")
def update():
    elapsed_seconds = 0
    if production_data["running"] and production_data["time_in_sec"] > 0:
        elapsed_seconds = int(time.time() - production_data["start_time"])
        count = elapsed_seconds // production_data["time_in_sec"]

        # Target reached
        if count >= production_data["target_count"]:
            start_time_dt = datetime.fromtimestamp(production_data["start_time"])
            stop_time_dt = datetime.now()

            # Detect shift
            start_hour = start_time_dt.hour + start_time_dt.minute / 60
            shift_name = "C"
            for s, (h_start, h_end) in shifts.items():
                if h_start < h_end:
                    if h_start <= start_hour < h_end:
                        shift_name = s
                else:
                    if start_hour >= h_start or start_hour < h_end:
                        shift_name = s

            # Save report
            report_history.append({
                "item": production_data["current_item"],
                "seconds_per_item": production_data["time_in_sec"],
                "count": production_data["target_count"],
                "start_time": start_time_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "stop_time": stop_time_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "total_seconds": production_data["target_count"] * production_data["time_in_sec"],
                "shift": shift_name
            })

            # Move to next item
            if production_data["items_queue"]:
                production_data["items_queue"].pop(0)

            if production_data["items_queue"]:
                nxt = production_data["items_queue"][0]
                production_data["current_item"] = nxt["item"]
                production_data["time_in_sec"] = nxt["seconds"]
                production_data["target_count"] = nxt["target_count"]
                production_data["count"] = 0
                production_data["start_time"] = time.time()
            else:
                production_data["running"] = False
                production_data["count"] = production_data["target_count"]

            save_data()
        else:
            production_data["count"] = count

    # Show last item if stopped
    if not production_data["running"] and production_data["items_queue"]:
        last_item = production_data["items_queue"][-1]
        current_item = last_item["item"]
        time_sec = last_item["seconds"]
        target_count = last_item["target_count"]
        count = 0
    else:
        current_item = production_data["current_item"]
        time_sec = production_data["time_in_sec"]
        target_count = production_data["target_count"]

    return jsonify({
        "current_item": current_item,
        "time_in_sec": time_sec,
        "count": production_data["count"],
        "target_count": target_count,
        "elapsed_seconds": elapsed_seconds,
        "running": production_data["running"]
    })

# Report page with proper filtering
@app.route("/report", methods=["GET"])
def report():
    filtered_reports = []

    from_date = request.args.get("from_date")
    to_date = request.args.get("to_date")
    report_type = request.args.get("report_type")
    month_filter = request.args.get("month")
    shift_filter = request.args.get("shift")

    # Only filter if at least one filter is provided
    if from_date or to_date or report_type:
        filtered_reports = report_history
        if from_date and to_date:
            filtered_reports = [r for r in filtered_reports if from_date <= r["start_time"][:10] <= to_date]
        if report_type == "month" and month_filter:
            filtered_reports = [r for r in filtered_reports if r["start_time"][:7] == month_filter]
        if report_type == "shift" and shift_filter:
            filtered_reports = [r for r in filtered_reports if r.get("shift") == shift_filter]

    return render_template("report.html", reports=filtered_reports, report_type=report_type)

# Edit item
@app.route("/edit_item/<int:idx>", methods=["GET", "POST"])
def edit_item(idx):
    item = production_data["items_queue"][idx]
    if request.method == "POST":
        item_name = request.form["item"]
        seconds = int(request.form["seconds"])
        target_count = int(request.form["total_count"])
        production_data["items_queue"][idx] = {
            "item": item_name,
            "seconds": seconds,
            "target_count": target_count
        }
        save_data()
        return redirect("/settings")
    return render_template("edit_item.html", idx=idx, item=item)

# Delete item
@app.route("/delete_item/<int:idx>", methods=["POST"])
def delete_item(idx):
    if 0 <= idx < len(production_data["items_queue"]):
        production_data["items_queue"].pop(idx)
        if not production_data["items_queue"]:
            production_data["current_item"] = ""
            production_data["time_in_sec"] = 0
            production_data["target_count"] = 0
            production_data["count"] = 0
            production_data["running"] = False
        save_data()
    return redirect("/settings")

# Current shift
@app.route("/current_shift")
def current_shift():
    now = datetime.now()
    current_hour = now.hour + now.minute / 60
    shift_name = "C"
    for s, (h_start, h_end) in shifts.items():
        if h_start < h_end:
            if h_start <= current_hour < h_end:
                shift_name = s
        else:
            if current_hour >= h_start or current_hour < h_end:
                shift_name = s
    return jsonify({"shift": shift_name})

# Export report to Excel
@app.route("/export_excel")
def export_excel():
    from_date = request.args.get("from_date")
    to_date = request.args.get("to_date")
    report_type = request.args.get("report_type")
    month_filter = request.args.get("month")
    shift_filter = request.args.get("shift")

    # Apply same filtering as /report
    filtered_reports = report_history
    if from_date or to_date or report_type:
        if from_date and to_date:
            filtered_reports = [r for r in filtered_reports if from_date <= r["start_time"][:10] <= to_date]
        if report_type == "month" and month_filter:
            filtered_reports = [r for r in filtered_reports if r["start_time"][:7] == month_filter]
        if report_type == "shift" and shift_filter:
            filtered_reports = [r for r in filtered_reports if r.get("shift") == shift_filter]

    if not filtered_reports:
        return "No data to export"

    df = pd.DataFrame(filtered_reports)
    df = df[["item", "seconds_per_item", "count", "start_time", "stop_time", "total_seconds", "shift"]]

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name="Report")
    output.seek(0)

    return send_file(output,
                     download_name="production_report.xlsx",
                     as_attachment=True,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ---------------- RUN -------------------
if __name__ == "__main__":
    app.run(debug=True)
