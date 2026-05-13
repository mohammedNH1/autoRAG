"""
Dashboard metrics, chart rendering, and audit-trail formatting.

The dashboard view is a thin orchestrator that calls `build_dashboard_context`
and renders the template. All the math lives here.
"""

from collections import Counter

from django.db.models import Count
from django.utils import timezone

from workspace.models import Message, WorkspaceActivity
from workspace.services import activity_log
from workspace.services.manage_members import user_display_name


# Based on the McKinsey-style estimate that employees spend 1.8 hours per
# day searching for and gathering information.
TIME_SAVED_MINUTES_PER_ACTIVE_DAY = 108

WEEKDAY_LABELS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
CHART_W, CHART_H, CHART_TOP, CHART_BOTTOM = 365, 80, 12, 62


# ---------------------------------------------------------------------------
# Pure formatters.
# ---------------------------------------------------------------------------
def smooth_svg_path(points):
    """Catmull-Rom-ish smoothing for the time-saved line chart."""
    path = f"M {points[0][0]:.2f} {points[0][1]:.2f}"
    for index, (p1, p2) in enumerate(zip(points, points[1:])):
        p0 = points[index - 1] if index else p1
        p3 = points[index + 2] if index + 2 < len(points) else p2
        c1x = p1[0] + (p2[0] - p0[0]) / 6
        c1y = p1[1] + (p2[1] - p0[1]) / 6
        c2x = p2[0] - (p3[0] - p1[0]) / 6
        c2y = p2[1] - (p3[1] - p1[1]) / 6
        path += f" C {c1x:.2f} {c1y:.2f}, {c2x:.2f} {c2y:.2f}, {p2[0]:.2f} {p2[1]:.2f}"
    return path


def format_time_saved(minutes):
    minutes = int(minutes or 0)
    if minutes < 60:
        return f"{minutes} {'min' if minutes == 1 else 'mins'}"
    hours = minutes / 60
    hours_value = int(hours) if hours.is_integer() else round(hours, 1)
    return f"{hours_value} {'hour' if hours_value == 1 else 'hours'}"


# ---------------------------------------------------------------------------
# Audit trail.
# ---------------------------------------------------------------------------
def build_audit_trail(workspace, limit=50):
    """Latest N workspace activities, shaped for the dashboard template."""
    rows = []
    activities = (
        WorkspaceActivity.objects
        .filter(workspace=workspace)
        .select_related("actor")
        .order_by("-created_at")[:limit]
    )
    for a in activities:
        rows.append({
            "action_label": activity_log.ACTION_LABELS.get(a.action, a.action),
            "action":       a.action,
            "actor_name":   user_display_name(a.actor) if a.actor else "System",
            "target":       a.target,
            "created_at":   a.created_at,
            "changes":      _format_config_changes(a.metadata.get("changes", []))
                            if a.action == "workspace.config_updated" else [],
            "metadata":     a.metadata,
        })
    return rows


def _format_config_changes(changes):
    """Pretty-print a config diff for the template (e.g. 'Temperature: 0.5 → 0.8')."""
    return [
        {
            "label":  activity_log.CONFIG_FIELD_LABELS.get(c.get("field"), c.get("field")),
            "before": c.get("before", ""),
            "after":  c.get("after", ""),
        }
        for c in changes
    ]


# ---------------------------------------------------------------------------
# Dashboard context — everything the dashboard.html template needs.
# ---------------------------------------------------------------------------
def build_dashboard_context(workspace, viewer, can_view_audit_trail):
    """
    Compute all dashboard metrics for `workspace` from the viewer's perspective.

    `can_view_audit_trail` is passed in (not computed here) so the permission
    rule stays alongside the rest of the settings policy in workspace_settings.
    """
    user_messages    = Message.objects.filter(session__workspace=workspace, sender="user")
    questions_count  = user_messages.count()
    timestamps       = list(user_messages.values_list("timestamp", flat=True))
    message_dates    = [timezone.localtime(ts).date() for ts in timestamps]
    active_days      = len(set(message_dates))
    week_ago         = timezone.now() - timezone.timedelta(days=7)
    questions_week   = user_messages.filter(timestamp__gte=week_ago).count()
    time_saved_min   = active_days * TIME_SAVED_MINUTES_PER_ACTIVE_DAY

    documents_qs     = workspace.documents.all()
    documents_count  = documents_qs.count()

    productive_days  = Counter(
        timezone.localtime(ts).strftime("%A") for ts in timestamps
    ).most_common(3)

    time_chart       = _build_time_chart(message_dates)

    audit_trail = build_audit_trail(workspace) if can_view_audit_trail else []

    return {
        "workspace":                    workspace,
        "workspace_id":                 workspace.workspace_id,
        "is_empty":                     questions_count == 0 and documents_count == 0,
        "questions_count":              questions_count,
        "questions_this_week":          questions_week,
        "documents_count":              documents_count,
        "docs_this_week":               documents_qs.filter(upload_time__gte=week_ago).count(),
        "time_saved_display":           format_time_saved(time_saved_min),
        "time_saved_this_week_display": format_time_saved(time_chart["this_week_minutes"]),
        "top_questions":                list(user_messages.values("text").annotate(c=Count("text")).order_by("-c", "text")[:5]),
        "top_documents":                list(documents_qs.order_by("-upload_time")[:5].values("document_title", "file")),
        "productive_days":              productive_days,
        "time_chart":                   time_chart["template"],
        "audit_trail":                  audit_trail,
        "can_view_audit_trail":         can_view_audit_trail,
    }


def _build_time_chart(message_dates):
    """
    Build the SVG path + tooltip data for the 7-day time-saved chart.

    Returns {"template": {...}, "this_week_minutes": int} — the caller
    needs the weekly total separately for the headline KPI.
    """
    today      = timezone.localdate()
    week_start = today - timezone.timedelta(days=(today.weekday() + 1) % 7)
    week_end   = week_start + timezone.timedelta(days=7)

    active_indexes = {
        (d - week_start).days for d in message_dates if week_start <= d < week_end
    }
    minutes = [
        TIME_SAVED_MINUTES_PER_ACTIVE_DAY if i in active_indexes else 0
        for i in range(7)
    ]
    this_week_minutes = sum(minutes)

    max_minutes = max(minutes) or 1
    points = [
        (i * CHART_W / 6, CHART_BOTTOM - minutes[i] / max_minutes * (CHART_BOTTOM - CHART_TOP))
        for i in range(7)
    ]
    line_path = smooth_svg_path(points)
    peak = max(range(7), key=lambda i: minutes[i]) if any(minutes) else min(max((today - week_start).days, 0), 6)
    peak_x, peak_y = points[peak]
    peak_date = week_start + timezone.timedelta(days=peak)
    day_suffix = "th" if 10 <= peak_date.day % 100 <= 20 else (
        {1: "st", 2: "nd", 3: "rd"}.get(peak_date.day % 10, "th")
    )

    return {
        "this_week_minutes": this_week_minutes,
        "template": {
            "days":          WEEKDAY_LABELS,
            "line":          line_path,
            "fill":          f"{line_path} L {CHART_W:.2f} {CHART_H:.2f} L 0.00 {CHART_H:.2f} Z",
            "dot_x":         f"{peak_x:.2f}",
            "dot_y":         f"{peak_y:.2f}",
            "tooltip_x":     f"{max(38, min(CHART_W - 38, peak_x)):.2f}",
            "tooltip_y":     f"{max(0, peak_y - 48):.2f}",
            "tooltip_value": format_time_saved(minutes[peak]),
            "tooltip_date":  f"{peak_date.strftime('%b')} {peak_date.day}{day_suffix}, {peak_date.year}",
        },
    }
