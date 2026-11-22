import type { TFunction } from 'i18next';

import type { ModifierGroupAdminOut } from '../../shared/types/api';

/** Human-readable selection rule of a modifier group. */
export function groupRuleText(group: ModifierGroupAdminOut, t: TFunction): string {
  if (group.selection_type === 'single') {
    return group.is_required
      ? t('admin.groups.ruleSingleRequired')
      : t('admin.groups.ruleSingleOptional');
  }
  return group.max_selections === null
    ? t('admin.groups.ruleMultipleUnlimited', { min: group.min_selections })
    : t('admin.groups.ruleMultiple', { min: group.min_selections, max: group.max_selections });
}
