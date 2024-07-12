import streamlit as st
import geopandas as gpd

from osm_utils import highway_priority
from utils import calculate_trip, display_map, TransportProfile, interpolate_color
import folium
from folium import FeatureGroup, plugins

from streamlit_folium import folium_static

st.set_page_config(layout="wide")

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
                                                      "on trasnsportation mode")
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
    streets = st.multiselect("Filter on street types", highway_priority, highway_priority)

if points_file is not None:
    points = gpd.read_file(points_file).reset_index(drop=True)

    if points.crs != 'EPSG:4326':
        points = points.to_crs('EPSG:4326')

    if not all(points.geometry.type == 'Point'):
        st.error("The uploaded GeoJSON must contain only points. Please upload a different file.")
    else:
        # Add filter options
        st.subheader("Filter Options")
        num_points = st.slider("Number of points to use", min_value=1, max_value=len(points),
                               value=min(100, len(points)))

        # Filter points
        filtered_points = points.head(num_points)

        # Expandable section for uploaded points
        with st.expander("View Uploaded Points"):
            display_map(filtered_points)

        if st.button("Start Trip Calculation"):
            with st.spinner("Calculating optimal trip..."):
                trip_gdf = calculate_trip(filtered_points,
                                          profile=profile,
                                          roundtrip=roundtrip,
                                          base_url=osmr_url,
                                          streets=streets,
                                          optimize_points=optimize_points)

            if trip_gdf is not None and not trip_gdf.empty:
                with (st.expander("View Calculated Trip", expanded=True)):
                    st.subheader("Map of Calculated Trip")

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
                        color = interpolate_color(idx / (len(trip_gdf) - 1), '#00ff00','#ff0000')
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

                    m.fit_bounds(m.get_bounds())
                    # color legend
                    st.markdown("""
                    <style>
                    .legend {
                        background: linear-gradient(to right, #ff0000, #00ff00);
                        height: 20px;
                        width: 200px;
                    }
                    </style>
                    <div>Legenda:</div>
                    <div class="legend"></div>
                    <div>Start ← → End</div>
                    """, unsafe_allow_html=True)
                    folium_static(m)

                    # statistics
                    total_distance = sum(line.length for line in trip_gdf.geometry) * 111  # Approximate km conversion
                    st.write(f"Total trip distance: {total_distance:.2f} km")

                    estimated_time = total_distance / profile.avg_speed
                    st.write(f"Estimated travel time: {estimated_time:.2f} hours")

                    trip_geojson = trip_gdf.to_json()

                    # download
                    st.download_button(
                        label="Download trip as GeoJSON",
                        data=trip_geojson,
                        file_name="trip.geojson",
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
