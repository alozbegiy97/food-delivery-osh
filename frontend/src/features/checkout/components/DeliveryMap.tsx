import 'leaflet/dist/leaflet.css';

import type { LatLngExpression, LeafletMouseEvent } from 'leaflet';
import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { CircleMarker, MapContainer, TileLayer, useMap, useMapEvents } from 'react-leaflet';

import { useTelegramVerticalSwipesDisabled } from '../../telegram/useTelegramVerticalSwipesDisabled';
import { toPoint, type MapPoint } from '../point';

// Osh city centre: the starting view when the restaurant has no coordinates.
const OSH_CENTER: [number, number] = [40.5283, 72.7985];

function ClickToPlace({ onPick }: { onPick: (point: MapPoint) => void }) {
  useMapEvents({
    click(event: LeafletMouseEvent) {
      onPick(toPoint(event.latlng.lat, event.latlng.lng));
    },
  });
  return null;
}

function FollowPoint({ point }: { point: MapPoint | null }) {
  const map = useMap();
  useEffect(() => {
    if (point) {
      map.panTo([Number(point.latitude), Number(point.longitude)]);
    }
  }, [map, point]);
  return null;
}

interface DeliveryMapProps {
  point: MapPoint | null;
  onPick: (point: MapPoint) => void;
  center?: [number, number] | null;
}

/**
 * Leaflet + OpenStreetMap, no API keys (DEC-01, DEC-94). The customer clicks
 * the delivery point; the text address is typed separately. The zone and the
 * fee are decided by the backend (PostGIS), never here.
 */
export function DeliveryMap({ point, onPick, center }: DeliveryMapProps) {
  const { t } = useTranslation();
  // Mini App only (no-op on the site): no swipe-to-close while the map is shown.
  useTelegramVerticalSwipesDisabled(true);
  const start: LatLngExpression = point
    ? [Number(point.latitude), Number(point.longitude)]
    : (center ?? OSH_CENTER);
  return (
    <div className="flex flex-col gap-2">
      <div
        className="h-72 overflow-hidden rounded-card border border-border"
        role="application"
        aria-label={t('checkout.map.label')}
      >
        <MapContainer center={start} zoom={13} scrollWheelZoom={false} className="h-full w-full">
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <ClickToPlace onPick={onPick} />
          <FollowPoint point={point} />
          {point && (
            <CircleMarker
              center={[Number(point.latitude), Number(point.longitude)]}
              radius={10}
              pathOptions={{ color: '#b45309', fillColor: '#f59e0b', fillOpacity: 0.8 }}
            />
          )}
        </MapContainer>
      </div>
      <p className="text-xs text-ink-600">
        {point
          ? t('checkout.map.picked', { lat: point.latitude, lng: point.longitude })
          : t('checkout.map.hint')}
      </p>
    </div>
  );
}
