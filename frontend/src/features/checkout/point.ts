export interface MapPoint {
  latitude: string;
  longitude: string;
}

/** NUMERIC(10,7) on the backend: at most 7 decimal places. */
export function toPoint(lat: number, lng: number): MapPoint {
  return { latitude: lat.toFixed(7), longitude: lng.toFixed(7) };
}
