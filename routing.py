from typing import Union, List, Optional

import requests
from requests.exceptions import MissingSchema, InvalidURL, Timeout

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
        base_url: str = 'http://router.project-osrm.org',
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
        base_url (str, optional): The base URL of the OSRM server. Defaults to 'http://router.project-osrm.org'.

    Returns:
        Optional[Union[List[LineString], requests.Response]]:
            - If successful, returns a list of LineString objects representing the route segments.
            - If the request fails, returns the Response object.
            - Returns None if no valid route is found or in case of other errors.

    Raises:
        ValueError: If the URL is invalid or the request fails.
        TimeoutError: If the request times out.

    Note:
        This function relies on external services and may fail due to network issues or service unavailability.
    """

    osrm_url = (
        f"{base_url}/trip/v1/{profile}/polyline({encoded_polyline})?"
        f"roundtrip={roundtrip}&source=first&destination=last&"
        f"steps={steps}&"
        f"geometries={geometries}&"
        f"overview={overview}&"
        f"annotations={annotations}"
    )

    try:
        response = requests.get(osrm_url)
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
    except (MissingSchema, InvalidURL):
        raise ValueError(f"Invalid URL: {base_url}")
    except Timeout as timeout_error:
        raise TimeoutError(f"Request timed out: {str(timeout_error)}") from timeout_error
    except requests.HTTPError as http_error:
        return http_error.response
    except requests.RequestException as req_error:
        raise ValueError(f"Request failed: {str(req_error)}") from req_error