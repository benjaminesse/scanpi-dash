import os
import yaml
import numpy as np
import pandas as pd
import plotly.express as px
from datetime import datetime
from flask import Flask
from dash import Dash, dcc, html
import dash_bootstrap_components as dbc
from dash.dependencies import Output, Input, State


# Read in the overall config file
with open("settings.yaml", "r") as ymlfile:
    config = yaml.load(ymlfile, Loader=yaml.FullLoader)

# Set possible plot items
plot_items = ["SO2", "O3", "int_av"]

# Get today's date
tday_date = datetime.now().date()

# Get the dates available
data_folders = os.listdir(f"{config['DataPath']}/Results")
data_folders.sort()
if len(data_folders) == 0:
    data_folders = [tday_date]
data_dates = pd.to_datetime(data_folders)
disabled_days = [d for d in pd.date_range(data_dates.min(), tday_date)
                 if d not in data_dates]

# Get the station status
try:
    with open(f"{config['DataPath']}/Station/status.txt", 'r') as r:
        status_time, status_text = r.readline().split(' - ')
        status_time = datetime.strptime(status_time, "%Y-%m-%d %H:%M:%S.%f"
                                        ).strftime("%Y-%m-%d %H:%M:%S")
except Exception as e:
    status_text, status_time = f'Unknown ({e})', '???'

# Generate the map plot
vlat, vlon = config['VentLocation']
slat, slon = config['ScannerLocation']
df = pd.DataFrame(
    {"lat": {
                config['StationName']: slat,
                config['VolcanoName']: vlat
             },
     "lon": {
                config['StationName']: slon,
                config['VolcanoName']: vlon
             },
     "color": {
                config['StationName']: "Red",
                config['VolcanoName']: "Blue"
     }
     }
)
print(config['MapZoom'])
map_fig = px.scatter_mapbox(
    df, lat="lat", lon="lon", zoom=config['MapZoom'],
    hover_name=df.index, hover_data=[],
    mapbox_style="stamen-terrain"
)
map_fig.update_layout(margin={"r": 0, "t": 0, "l": 0, "b": 0})

# Setup the Dash app
server = Flask(__name__)
app = Dash(__name__, server=server, external_stylesheets=[dbc.themes.DARKLY])
app.title = f"{config['StationName']} Dashboard"

# =============================================================================
# =============================================================================
# App Layout
# =============================================================================
# =============================================================================

controls = dbc.Card(
    [
        html.Div(
            [
                dcc.DatePickerSingle(
                    id="date-picker",
                    min_date_allowed=data_dates.min().date(),
                    max_date_allowed=tday_date,
                    initial_visible_month=tday_date,
                    date=tday_date,
                    display_format="YYYY/MM/DD",
                    disabled_days=disabled_days
                )
            ],
            className="dash-bootstrap"
        ),

        html.Div(
            [
                dbc.Label("Plot Parameter"),
                dcc.Dropdown(
                    id="param-filter",
                    options=[{"label": plot_param, "value": plot_param}
                             for plot_param in plot_items],
                    value="SO2",
                    clearable=False,
                    searchable=False,
                    className="dropdown"
                )
            ]
        ),

        html.Hr(),

        html.Div(
            [
                dbc.Label("Upper Limit"),
                dbc.Input(id='clim-hi', type='number', placeholder="-")
            ]
        ),

        html.Div(
            [
                dbc.Label("Lower Limit"),
                dbc.Input(id='clim-lo', type='number', placeholder="-")
            ]
        ),

        html.Hr(),

        html.Div(
            [
                dbc.Button("View logs", id="open", color="primary"),

                dbc.Modal(
                    [
                        dbc.ModalHeader("Station logs"),
                        dbc.ModalBody(
                            dbc.Textarea(rows=10, id="log-text")
                        ),
                        dbc.ModalFooter(
                            dbc.Button(
                                "Close",
                                id="close",
                                className="ml-auto"
                            )
                        )
                    ],
                    id="modal",
                    is_open=False,
                    size="xl",
                    backdrop=True,
                    scrollable=True,
                    centered=True,
                    fade=True
                ),

                dbc.Button("Refresh", id="refresh", color="primary",
                           style={"margin-left": "15px"})
            ]
        )
    ],
    body=True
)

plots = dbc.Card(
    [
        html.Div(
            dcc.Graph(id="param-chart")
        ),
        html.Div(
            dcc.Graph(id="map-chart", figure=map_fig)
        )
    ],
    body=True
)

app.layout = dbc.Container(
    [
        html.H1(f"{config['StationName']} Dashboard"),
        html.H5(f"Current status: {status_text} (at {status_time})"),
        html.Hr(),
        dbc.Row(
            [
                dbc.Col(controls, md=4),
                dbc.Col(plots, md=8),
            ]
        )
    ],
    fluid=True
)


# =============================================================================
# Server Callbacks
# =============================================================================

@app.callback(
    Output("param-chart", "figure"),
    [
        Input("date-picker", "date"),
        Input("param-filter", "value"),
        Input("clim-hi", "value"),
        Input("clim-lo", "value"),
        Input("refresh", "n_clicks")
    ]
)
def generate_plot(plot_date, plot_param, climhi, climlo, n):
    """Callback to plot selected data."""
    fpath = f"{config['DataPath']}/Results/"

    try:
        scan_fnames = os.listdir(
            f"{fpath}/{plot_date}/so2")
    except FileNotFoundError:
        df = pd.DataFrame(
            index=np.arange(0),
            columns=["Scan Time [UTC]", "Scan Angle", plot_param]
        )
        fig = px.scatter(df, x="Scan Time [UTC]", y="Scan Angle",
                         color=plot_param, range_color=[0, 1])
        return fig

    # Initialize the DataFrame
    df = pd.DataFrame(index=np.arange(len(scan_fnames)*99),
                      columns=["Scan Time [UTC]", "Scan Angle", plot_param])
    n = 0

    # Iterate through the files
    for i, fname in enumerate(scan_fnames):

        # Pull year, month and day from file name
        y = int(fname[:4])
        m = int(fname[4:6])
        d = int(fname[6:8])

        # Load the scan file, unpacking the angle and SO2 data
        try:
            scan_df = pd.read_csv(f"{fpath}/{plot_date}/so2/{fname}")
        except pd.errors.EmptyDataError:
            continue

        # Pull the time and convert to a timestamp
        for j, t in enumerate(scan_df["Time"]):
            try:
                H = int(t)
                M = int((t - H)*60)
                S = int((t-H-M/60))*3600
                ts = pd.Timestamp(year=y, month=m, day=d, hour=H, minute=M,
                                  second=S)

                # Set the next row
                df.iloc[n] = [ts, scan_df["Angle"].iloc[j],
                              scan_df[plot_param].iloc[j]]

            except ValueError:
                pass

            # Iterate the counter
            n += 1

    # Remove row with nan times
    df = df[df["Scan Time [UTC]"].notna()]

    # Set nan values to zero
    df = df.fillna(0)

    # Set the limits
    if climlo is None:
        climlo = df[plot_param].min()
    if climhi is None:
        climlo = df[plot_param].max()
    limits = [climlo, climhi]

    # Generate the figure
    fig = px.scatter(df, x="Scan Time [UTC]", y="Scan Angle", color=plot_param,
                     range_color=limits)

    return fig


@app.callback(
    Output("modal", "is_open"),
    [Input("open", "n_clicks"), Input("close", "n_clicks")],
    State("modal", "is_open")
)
def toggle_modal(n1, n2, is_open):
    if n1 or n2:
        return not is_open
    return is_open


@app.callback(
    Output("log-text", "value"),
    Input("date-picker", "date")
)
def update_log_text(date):
    # Try to read the log file
    fname = f"{config['DataPath']}/Results/{date}/{date}.log"
    try:
        with open(fname, "r") as r:
            lines = r.readlines()
        log_text = ""
        for line in lines:
            log_text += line.strip() + "\n"
    except FileNotFoundError:
        log_text = f"Log file {fname} not found!"

    return log_text


if __name__ == "__main__":
    app.run_server(debug=True)