import 'leaflet/dist/leaflet.css';
import './leafletGlobal';
import '@geoman-io/leaflet-geoman-free';
import '@geoman-io/leaflet-geoman-free/dist/leaflet-geoman.css';

import L from 'leaflet';
import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { MapContainer, TileLayer, useMap } from 'react-leaflet';

export interface ZoneGeometry {
  type: 'Polygon' | 'MultiPolygon';
  coordinates: unknown[];
}

export interface OtherZone {
  id: string;
  name: string;
  isActive: boolean;
  boundary: ZoneGeometry | null;
}

const OSH_CENTER: [number, number] = [40.5283, 72.7985];

/** Read-only outlines of the other zones (Geoman ignores them). */
function OtherZones({ zones }: { zones: OtherZone[] }) {
  const map = useMap();
  useEffect(() => {
    const layer = L.geoJSON(undefined, {
      pmIgnore: true,
      style: (feature) => ({
        color: feature?.properties?.active ? '#0f766e' : '#9ca3af',
        weight: 2,
        dashArray: feature?.properties?.active ? undefined : '6 4',
        fillOpacity: 0.08,
      }),
    } as L.GeoJSONOptions);
    for (const zone of zones) {
      if (zone.boundary) {
        layer.addData({
          type: 'Feature',
          properties: { active: zone.isActive, name: zone.name },
          geometry: zone.boundary as GeoJSON.Geometry,
        } as GeoJSON.Feature);
      }
    }
    layer.eachLayer((l) => {
      const name = (l as L.Layer & { feature?: GeoJSON.Feature }).feature?.properties?.name;
      if (name) {
        l.bindTooltip(String(name));
      }
    });
    layer.addTo(map);
    return () => {
      layer.remove();
    };
  }, [map, zones]);
  return null;
}

/** The edited zone: draw, edit or remove polygons with Geoman (DEC-94). */
function Editor({
  initial,
  onChange,
}: {
  initial: ZoneGeometry | null;
  onChange: (geometry: ZoneGeometry | null) => void;
}) {
  const map = useMap();
  useEffect(() => {
    const group = L.featureGroup().addTo(map);
    const emit = () => {
      const polygons: unknown[] = [];
      group.eachLayer((layer) => {
        const geometry = (layer as L.Polygon).toGeoJSON().geometry;
        if (geometry.type === 'Polygon') {
          polygons.push(geometry.coordinates);
        } else if (geometry.type === 'MultiPolygon') {
          polygons.push(...geometry.coordinates);
        }
      });
      onChange(polygons.length ? { type: 'MultiPolygon', coordinates: polygons } : null);
    };
    if (initial) {
      L.geoJSON(initial as GeoJSON.Geometry).eachLayer((layer) => {
        group.addLayer(layer);
        layer.on('pm:edit', emit);
      });
      if (group.getLayers().length) {
        map.fitBounds(group.getBounds(), { padding: [24, 24] });
      }
    }
    map.pm.setGlobalOptions({ layerGroup: group });
    map.pm.addControls({
      position: 'topleft',
      drawMarker: false,
      drawCircleMarker: false,
      drawPolyline: false,
      drawCircle: false,
      drawText: false,
      drawRectangle: true,
      drawPolygon: true,
      editMode: true,
      dragMode: false,
      cutPolygon: false,
      rotateMode: false,
      removalMode: true,
    });
    const onCreate = (event: { layer: L.Layer }) => {
      event.layer.on('pm:edit', emit);
      emit();
    };
    const onRemove = () => emit();
    map.on('pm:create', onCreate);
    map.on('pm:remove', onRemove);
    return () => {
      map.off('pm:create', onCreate);
      map.off('pm:remove', onRemove);
      map.pm.removeControls();
      group.remove();
    };
    // The editor is re-created for every zone (keyed by the page).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map]);
  return null;
}

interface ZoneMapProps {
  initial: ZoneGeometry | null;
  others: OtherZone[];
  onChange: (geometry: ZoneGeometry | null) => void;
}

/** Leaflet + OpenStreetMap + Geoman; geometry is validated by the backend
 * (PostGIS, DEC-53) — the map never decides validity or overlaps. */
export function ZoneMap({ initial, others, onChange }: ZoneMapProps) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-2">
      <div
        className="h-96 overflow-hidden rounded-card border border-border"
        role="application"
        aria-label={t('admin.zones.mapLabel')}
      >
        <MapContainer
          center={OSH_CENTER}
          zoom={12}
          scrollWheelZoom={false}
          className="h-full w-full"
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <OtherZones zones={others} />
          <Editor initial={initial} onChange={onChange} />
        </MapContainer>
      </div>
      <p className="text-xs text-ink-600">{t('admin.zones.mapHint')}</p>
    </div>
  );
}
