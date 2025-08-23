# ABOUTME: Shared HTML generation utilities for dashboard widgets
# ABOUTME: Provides consistent error displays, progress bars, and styling

def generate_error_html(error_msg, title="Data Unavailable", additional_info=None, max_msg_length=100):
    """Generate consistent error display HTML."""
    truncated_msg = error_msg[:max_msg_length] if error_msg else "Unknown error"
    
    additional_html = ""
    if additional_info:
        additional_html = f"""
        <div style="color: #7f1d1d; font-size: 9px; margin-top: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
            {additional_info}
        </div>"""
    
    return f"""
    <div style="
        display: flex;
        align-items: center;
        justify-content: center;
        height: 100%;
        background: #fef2f2;
        border-radius: 8px;
        padding: 10px;
        font-family: 'Amazon Ember', -apple-system, sans-serif;
        overflow: hidden;
        box-sizing: border-box;
    ">
        <div style="text-align: center; width: 100%; overflow: hidden;">
            <div style="color: #991b1b; font-weight: 600; font-size: 14px;">
                {title}
            </div>
            <div style="color: #7f1d1d; font-size: 10px; margin-top: 4px; word-wrap: break-word; overflow: hidden; text-overflow: ellipsis;">
                {truncated_msg}
            </div>
            {additional_html}
        </div>
    </div>
    """


def generate_no_data_html(message="No data available for this time range", subtitle=None):
    """Generate consistent no-data display HTML."""
    subtitle_html = f"""
    <div style="font-size: 12px; margin-top: 8px; opacity: 0.8;">
        {subtitle}
    </div>""" if subtitle else ""
    
    return f"""
    <div style="
        display: flex;
        align-items: center;
        justify-content: center;
        height: 100%;
        background: linear-gradient(135deg, #6b7280 0%, #4b5563 100%);
        border-radius: 8px;
        padding: 20px;
        font-family: 'Amazon Ember', -apple-system, sans-serif;
    ">
        <div style="text-align: center; color: white;">
            <div style="font-size: 16px; font-weight: 600;">{message}</div>
            {subtitle_html}
        </div>
    </div>
    """


def generate_progress_bar(percentage, height=20, show_text=True, color=None):
    """Generate an HTML progress bar."""
    if color is None:
        color = get_status_color(percentage)
    
    text_html = f"""
        <div style="
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 100%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: {min(11, height-4)}px;
            font-weight: 600;
            color: white;
            text-shadow: 0 1px 2px rgba(0,0,0,0.3);
        ">{percentage:.0f}%</div>
    """ if show_text else ""
    
    return f"""
    <div style="
        width: 100%;
        height: {height}px;
        background: rgba(0,0,0,0.1);
        border-radius: {min(10, height//2)}px;
        overflow: hidden;
        position: relative;
    ">
        <div style="
            width: {min(percentage, 100):.0f}%;
            height: 100%;
            background: linear-gradient(90deg, 
                {color} 0%, 
                {color}dd 100%);
            transition: width 0.3s ease;
        "></div>
        {text_html}
    </div>
    """


def get_status_color(percentage):
    """Get color based on usage percentage thresholds."""
    if percentage >= 90:
        return "#ef4444"  # Red
    elif percentage >= 70:
        return "#f59e0b"  # Yellow
    else:
        return "#10b981"  # Green


def generate_metric_card(value, label, color=None, gradient=True, font_size=None):
    """Generate a metric display card with value and label."""
    if color is None:
        color = "#10b981"  # Default green
    
    if font_size is None:
        font_size = 30
    
    background = f"linear-gradient(135deg, {color} 0%, {color}aa 100%)" if gradient else color
    
    return f"""
    <div style="
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        height: 100%;
        font-family: 'Amazon Ember', -apple-system, sans-serif;
        background: {background};
        border-radius: 8px;
        padding: 10px;
        box-sizing: border-box;
        overflow: hidden;
    ">
        <div style="
            font-size: {font_size}px;
            font-weight: 700;
            color: white;
            text-shadow: 0 2px 4px rgba(0,0,0,0.2);
            margin-bottom: 4px;
            line-height: 1;
        ">{value}</div>
        <div style="
            font-size: 12px;
            color: rgba(255,255,255,0.9);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            font-weight: 500;
            line-height: 1;
        ">{label}</div>
    </div>
    """