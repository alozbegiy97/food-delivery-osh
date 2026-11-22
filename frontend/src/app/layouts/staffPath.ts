// Staff areas (admin, kitchen under /admin, courier) keep the previous header
// and footer; the "Печь" header and footer are for the public site only
// (DEC-161 rev. 47). Only the path decides: roles are checked by the routes
// and, again, by every API.
const STAFF_PATH = /^\/(admin|courier)(\/|$)/;

export function isStaffPath(pathname: string): boolean {
  return STAFF_PATH.test(pathname);
}
