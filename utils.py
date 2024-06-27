import folium
import streamlit as st
from streamlit_folium import folium_static
from folium.plugins import MarkerCluster




def calculate_trip(gdf):
    # TODO: Add logic here
    return gdf


def display_map(gdf):
    # Display the map
        st.subheader("Map Visualization")
        
        # Create a Folium map
        m = folium.Map(location=[gdf.geometry.y.mean(), 
                                 gdf.geometry.x.mean()], 
                       zoom_start=10)
        
        # Create a MarkerCluster
        marker_cluster = MarkerCluster().add_to(m)
        
        # Add points to the map with popup information
        for idx, row in gdf.iterrows():
            # Create popup content
            popup_content = "<br>".join([f"{col}: {val}" for col, val in row.items() if col != 'geometry'])
            
            # Add marker
            folium.Marker(
                location=[row.geometry.y, row.geometry.x],
                popup=folium.Popup(popup_content, max_width=300),
                tooltip=f"Point {idx}"
            ).add_to(marker_cluster)
        
        # Fit the map to the bounds of the data
        m.fit_bounds(m.get_bounds())
        
        # Display the map in Streamlit
        folium_static(m)
        
        # Display GeoDataFrame as a table
        st.subheader("Data Table")
        st.dataframe(gdf.drop(columns=['geometry'], errors="ignore"))
    