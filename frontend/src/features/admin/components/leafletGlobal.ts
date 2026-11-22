import L from 'leaflet';

// Leaflet-Geoman registers itself on the global `L` (DEC-94); ES modules do
// not create it, so it is set here, imported before Geoman.
declare global {
  interface Window {
    L: typeof L;
  }
}

window.L = L;
