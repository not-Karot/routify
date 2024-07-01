from typing import Union, List, Optional

import requests

from shapely.geometry import LineString
import polyline


def get_osrm_trip(
        encoded_polyline: str,
        profile: str = 'driving',
        steps: str = 'true',
        geometries: str = 'polyline',
        overview: str = 'full',
        annotations: str = 'true',
        roundtrip: str = 'false',
        base_url: str = 'http://localhost:5000'
) -> Optional[Union[List[LineString], requests.Response]]:
    """
    Fetch and process an OSRM trip based on the given parameters.

    This function sends a request to the OSRM server to calculate a trip route
    based on the provided encoded polyline. It then processes the response to
    extract the route geometries.

    Args:
        encoded_polyline (str): The encoded polyline representing the route points.
        profile (str, optional): The routing profile to use. Defaults to 'driving'.
        steps (str, optional): Whether to include steps in the response. Defaults to 'true'.
        geometries (str, optional): The geometry format for the response. Defaults to 'polyline'.
        overview (str, optional): The type of overview geometry to include. Defaults to 'full'.
        annotations (str, optional): Whether to include annotations. Defaults to 'true'.
        roundtrip (str, optional): Whether the trip should return to the start point. Defaults to 'false'.
        base_url (str, optional): The base URL of the OSRM server. Defaults to 'http://localhost:5000'.

    Returns:
        Optional[Union[List[LineString], requests.Response]]:
            - If successful, returns a list of LineString objects representing the route segments.
            - If the request fails, returns the Response object.
            - Returns None if no valid route is found or in case of other errors.

    Raises:
        Any exceptions raised by the requests library are not caught and will propagate.
    """

    osrm_url = (
        f"{base_url}/trip/v1/{profile}/polyline({encoded_polyline})?"
        f"roundtrip={roundtrip}&source=first&destination=last&"
        f"steps={steps}&geometries={geometries}&overview={overview}&annotations={annotations}"
    )

    response = requests.get(osrm_url)
    print(response)
    if response.status_code == 200:
        data = response.json()
        trips = data.get('trips', [])
        routes = []
        for trip in trips:
            for leg in trip.get('legs', []):
                for step in leg.get('steps', []):
                    encoded_polyline = step.get('geometry', '')
                    if encoded_polyline:
                        decoded_route = polyline.decode(encoded_polyline)
                        if len(decoded_route) > 1:
                            routes.append(LineString([(lon, lat) for lat, lon in decoded_route]))

        return routes if routes else None
    else:
        return response
