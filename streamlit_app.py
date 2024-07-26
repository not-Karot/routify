import streamlit as st
import geopandas as gpd
import folium
from folium import FeatureGroup, plugins
from streamlit_folium import folium_static
from shapely import Point

from osm_utils import highway_priority
from utils import calculate_trip, TransportProfile, interpolate_color, recalculate_uncovered_points


def create_trip_map(trip_gdf, filtered_points, uncovered_points, verify_coverage):
    bounds = trip_gdf.total_bounds
    center = [(bounds[1] + bounds[3]) / 2, (bounds[0] + bounds[2]) / 2]

    m = folium.Map(location=center, zoom_start=10)

    lines_group = FeatureGroup(name="Route")
    points_group = FeatureGroup(name='Points')
    markers_group = FeatureGroup(name='Markers')

    for idx, row in filtered_points.iterrows():
        folium.CircleMarker(
            [row.geometry.y, row.geometry.x],
            radius=5,
            popup=f"Point {idx}",
            color="blue",
            fill=True,
            fillColor="blue"
        ).add_to(points_group)

    folium.Marker(
        [trip_gdf.iloc[0].geometry.coords[0][1], trip_gdf.iloc[0].geometry.coords[0][0]],
        popup="Start",
        icon=folium.Icon(color="green", icon="play"),
    ).add_to(markers_group)

    folium.Marker(
        [trip_gdf.iloc[-1].geometry.coords[-1][1], trip_gdf.iloc[-1].geometry.coords[-1][0]],
        popup="End",
        icon=folium.Icon(color="red", icon="stop"),
    ).add_to(markers_group)

    for idx, row in trip_gdf.iterrows():
        color = interpolate_color(idx / (len(trip_gdf) - 1), '#00ff00', '#ff0000')
        pol = folium.PolyLine(
            locations=[(y, x) for x, y in row.geometry.coords],
            color=color,
            weight=3,
            opacity=0.8,
            tooltip=f'Segment {idx}',
        )
        pol.add_to(lines_group)

        plugins.PolyLineTextPath(
            polyline=pol,
            text='→',
            repeat=True,
            offset=1,
            attributes={'fill': '#000000', 'font-weight': 'bold', 'font-size': '34'}
        ).add_to(lines_group)
        plugins.PolyLineTextPath(
            polyline=pol,
            center=False,
            text=str(idx),
            repeat=False,
            offset=2,
            attributes={'fill': '#000000', 'font-weight': 'bold', 'font-size': '24'}
        ).add_to(lines_group)

    m.add_child(lines_group)
    m.add_child(points_group)
    m.add_child(markers_group)

    if verify_coverage and uncovered_points is not None and not uncovered_points.empty:
        uncovered_group = FeatureGroup(name='Uncovered Points')
        for idx, row in uncovered_points.iterrows():
            folium.CircleMarker(
                [row.geometry.y, row.geometry.x],
                radius=5,
                popup=f"Uncovered Point {idx}",
                color="red",
                fill=True,
                fillColor="red"
            ).add_to(uncovered_group)
        m.add_child(uncovered_group)

    m.fit_bounds(m.get_bounds())
    return m


def display_trip_statistics(trip_gdf, profile, verify_coverage, uncovered_points, max_distance):
    total_distance = sum(line.length for line in trip_gdf.geometry) * 111  # Approximate km conversion
    st.write(f"Total trip distance: {total_distance:.2f} km")

    estimated_time = total_distance / profile.avg_speed
    st.write(f"Estimated travel time: {estimated_time:.2f} hours")

    if verify_coverage:
        if uncovered_points is not None and not uncovered_points.empty:
            st.warning(
                f"{len(uncovered_points)} points were not covered by the calculated route (max distance: {max_distance} meters).")
        else:
            st.success(f"All points were covered by the calculated route (max distance: {max_distance} meters).")


st.set_page_config(layout="wide")

# Initialize session state variables
if 'trip_calculated' not in st.session_state:
    st.session_state.trip_calculated = False
if 'trip_gdf' not in st.session_state:
    st.session_state.trip_gdf = None
if 'uncovered_points' not in st.session_state:
    st.session_state.uncovered_points = None
if 'filtered_points' not in st.session_state:
    st.session_state.filtered_points = None
if 'verify_coverage' not in st.session_state:
    st.session_state.verify_coverage = True
if 'max_distance' not in st.session_state:
    st.session_state.max_distance = 10
if 'previous_transport_mode' not in st.session_state:
    st.session_state.previous_transport_mode = None
if 'previous_optimize_points' not in st.session_state:
    st.session_state.previous_optimize_points = None
if 'previous_roundtrip' not in st.session_state:
    st.session_state.previous_roundtrip = None
if 'previous_osmr_url' not in st.session_state:
    st.session_state.previous_osmr_url = None


# Callback for max_distance slider
def update_uncovered_points():
    if st.session_state.trip_calculated and st.session_state.verify_coverage:
        st.session_state.uncovered_points = recalculate_uncovered_points(
            st.session_state.trip_gdf,
            st.session_state.filtered_points,
            st.session_state.max_distance
        )


# Function to reset trip calculation
def reset_trip_calculation():
    st.session_state.trip_calculated = False
    st.session_state.trip_gdf = None
    st.session_state.uncovered_points = None


st.title('Routify')
st.info("This app lets you upload a series of Points and provides you with an optimal-like trip "
        "to visit all of them at least once.")

col1, col2 = st.columns(2)

with col1:
    points_file = st.file_uploader("Choose a GeoJSON file with points", type="geojson")

with col2:
    osrm_servers = [
        'https://router.project-osrm.org',
        'https://routing.openstreetmap.de/routed-foot/',
        'https://routing.openstreetmap.de/routed-bike/',
        'https://routing.openstreetmap.de/routed-car/',
        'Custom'
    ]

    default_profile_options = TransportProfile.get_all_osrm_profiles()

    # Create a selectbox for choosing the OSRM server
    selected_server = st.selectbox("Select OSRM server:", osrm_servers)

    use_profile_placeholder = False
    profile_mapping = {}

    # If 'Custom' is selected, show a text input for custom URL
    if selected_server == 'Custom':
        osmr_url = st.text_input("Enter custom OSRM server URL:", "https://example-{}.com")
        use_profile_placeholder = st.checkbox("Use profile placeholder in URL", value=True)

        if use_profile_placeholder:
            if osmr_url.count('{}') != 1 and osmr_url.count('{profile}') != 1:
                st.error("The URL must contain exactly one placeholder marked with {} or {profile}.")
            else:
                # If the placeholder is {profile}, replace it with {}
                osmr_url = osmr_url.replace('{profile}', '{}')

                st.write("Map transport modes to OSRM profiles:")
                for profile in TransportProfile:
                    mapped_value = st.text_input(f"Map {profile.display_name} to:",
                                                 value=profile.osrm_profile,
                                                 key=f"profile_map_{profile.name}",
                                                 help="This field will update the url to ping the right server based "
                                                      "on transportation mode")
                    profile_mapping[profile] = mapped_value
    else:
        osmr_url = selected_server

    st.write("Transportation Options:")
    transport_mode_display = st.radio("Select transportation mode:",
                                      [profile.display_name for profile in TransportProfile])

    profile = TransportProfile.get_by_display_name(transport_mode_display)

    if use_profile_placeholder and selected_server == 'Custom':
        placeholder_value = profile_mapping.get(profile, profile.osrm_profile)
        osmr_url = osmr_url.format(placeholder_value)
        st.write(f"Final URL: {osmr_url}")
    else:
        st.write(f"Final URL: {osmr_url}")

    optimize_points = st.toggle("Optimize points", value=False, help="Whether to provide all points to trip calculator "
                                                                     "or reduce them in number, this may cause some "
                                                                     "unpredictable behavior ")
    roundtrip = st.checkbox("Make it a roundtrip", value=False)
    verify_coverage = st.checkbox("Verify point coverage", value=st.session_state.verify_coverage,
                                  key='verify_coverage')

    if verify_coverage:
        max_distance = st.slider("Maximum distance for point coverage (meters)",
                                 min_value=1, max_value=100, value=st.session_state.max_distance, step=1,
                                 key='max_distance', on_change=update_uncovered_points)
    else:
        max_distance = None

    if optimize_points:
        streets = st.multiselect("Filter on street types", highway_priority, highway_priority)
    else:
        streets = highway_priority

    # Check if any of the key parameters have changed
    if (transport_mode_display != st.session_state.previous_transport_mode or
            optimize_points != st.session_state.previous_optimize_points or
            roundtrip != st.session_state.previous_roundtrip or
            osmr_url != st.session_state.previous_osmr_url):
        reset_trip_calculation()

    # Update the previous state
    st.session_state.previous_transport_mode = transport_mode_display
    st.session_state.previous_optimize_points = optimize_points
    st.session_state.previous_roundtrip = roundtrip
    st.session_state.previous_osmr_url = osmr_url

if points_file is not None:
    points = gpd.read_file(points_file).reset_index(drop=True)

    if points.crs != 'EPSG:4326':
        points = points.to_crs('EPSG:4326')

    if not all(points.geometry.type == 'Point'):
        st.error("The uploaded GeoJSON must contain only points. Please upload a different file.")
    else:
        # Filter options
        st.subheader("Filter Options")
        num_points = st.slider("Number of points to use", min_value=1, max_value=len(points),
                               value=min(100, len(points)))

        # Filter points
        filtered_points = points.head(num_points)

        # Expandable section for uploaded points
        with st.expander("View Uploaded Points"):
            m = folium.Map(location=[filtered_points.geometry.y.mean(), filtered_points.geometry.x.mean()],
                           zoom_start=10)
            for idx, row in filtered_points.iterrows():
                folium.Marker([row.geometry.y, row.geometry.x], popup=f"Point {idx}").add_to(m)
            folium_static(m)

        # Add toggle for point selection
        select_specific_points = st.toggle("Select specific start and end points", value=False)

        start_point = None
        end_point = None

        if select_specific_points:
            st.subheader("Select Start and End Points")

            start_index = st.selectbox("Select start point:", range(len(filtered_points)),
                                       format_func=lambda
                                           x: f"Point {x}: ({filtered_points.iloc[x].geometry.y:.6f}, {filtered_points.iloc[x].geometry.x:.6f})")
            start_point = filtered_points.iloc[start_index].geometry

            end_index = st.selectbox("Select end point:", range(len(filtered_points)),
                                     format_func=lambda
                                         x: f"Point {x}: ({filtered_points.iloc[x].geometry.y:.6f}, {filtered_points.iloc[x].geometry.x:.6f})")
            end_point = filtered_points.iloc[end_index].geometry

            # Display selected points
            st.write(f"Start point selected: {start_point.y:.6f}, {start_point.x:.6f}")
            st.write(f"End point selected: {end_point.y:.6f}, {end_point.x:.6f}")
        else:
            st.info("Using all points without specific start and end selection.")

        if st.button("Start Trip Calculation") or st.session_state.trip_calculated:
            if not st.session_state.trip_calculated:
                with st.spinner("Calculating optimal trip..."):
                    st.session_state.filtered_points = filtered_points
                    st.session_state.trip_gdf, st.session_state.uncovered_points = calculate_trip(
                        filtered_points,
                        profile=profile,
                        roundtrip=roundtrip,
                        base_url=osmr_url,
                        streets=streets,
                        optimize_points=optimize_points,
                        start_point=start_point,
                        end_point=end_point,
                        max_distance=max_distance if verify_coverage else None
                    )
                    st.session_state.trip_calculated = True

            if st.session_state.trip_gdf is not None and not st.session_state.trip_gdf.empty:
                with st.expander("View Calculated Trip", expanded=True):
                    st.subheader("Map of Calculated Trip")

                    # Create and display the map
                    m = create_trip_map(st.session_state.trip_gdf, filtered_points, st.session_state.uncovered_points,
                                        verify_coverage)
                    folium_static(m)

                    # Display statistics
                    display_trip_statistics(st.session_state.trip_gdf, profile, verify_coverage,
                                            st.session_state.uncovered_points, max_distance)

                    # Download buttons
                    col1, col2 = st.columns(2)

                    with col1:
                        trip_geojson = st.session_state.trip_gdf.to_json()
                        st.download_button(
                            label="Download trip as GeoJSON",
                            data=trip_geojson,
                            file_name="trip.geojson",
                            mime="application/json"
                        )

                    with col2:
                        if st.session_state.uncovered_points is not None and not st.session_state.uncovered_points.empty:
                            uncovered_geojson = st.session_state.uncovered_points.to_json()
                            st.download_button(
                                label="Download uncovered points as GeoJSON",
                                data=uncovered_geojson,
                                file_name="uncovered_points.geojson",
                                mime="application/json"
                            )
            else:
                st.error("Failed to calculate the trip. Please try again.")

# Add some instructions and information
st.sidebar.header("How to use:")
st.sidebar.write("""
1. Upload a GeoJSON file containing points.
2. Select your transportation mode.
3. Choose whether you want a roundtrip.
4. Adjust the number of points to use with the slider.
5. Click 'Start Trip Calculation'.
6. View your optimized route and trip statistics.
7. Download the route as a GeoJSON file if desired.
""")

st.sidebar.header("About:")
st.sidebar.write("""
This app uses the OSM (Open Street Map) to calculate optimal routes between multiple points. 
It's perfect for planning trips, deliveries, or any scenario where you need to visit multiple locations efficiently.
""")
