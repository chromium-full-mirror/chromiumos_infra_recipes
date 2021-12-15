# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf import json_format

from recipe_engine import recipe_test_api

from PB.chromite.api.android import MarkStableResponse
from PB.chromite.api.android import MarkStableStatusType
from PB.chromite.api.android import WriteLKGBResponse


class AndroidApiTestApi(recipe_test_api.RecipeTestApi):

  @property
  def android_package(self):
    return 'android-package'

  @property
  def android_version(self):
    return '7123456'

  def _mark_stable_response(self, status):
    response = MarkStableResponse(status=status)
    if status == MarkStableStatusType.MARK_STABLE_STATUS_SUCCESS:
      response.android_atom.category = 'chromeos-base'
      response.android_atom.package_name = self.android_package
      response.android_atom.version = '%s-r1' % self.android_version

    return self.m.cros_build_api.set_api_return(
        'uprev android', 'AndroidService/MarkStable',
        json_format.MessageToJson(response))

  def set_mark_stable_success(self):
    return self._mark_stable_response(
        MarkStableStatusType.MARK_STABLE_STATUS_SUCCESS)

  def set_mark_stable_pinned(self):
    return self._mark_stable_response(
        MarkStableStatusType.MARK_STABLE_STATUS_PINNED)

  def set_mark_stable_early_exit(self):
    return self._mark_stable_response(
        MarkStableStatusType.MARK_STABLE_STATUS_EARLY_EXIT)

  def set_write_lkgb_response(self, modified_files):
    response = WriteLKGBResponse(modified_files=modified_files)
    return self.m.cros_build_api.set_api_return(
        'write android lkgb', 'AndroidService/WriteLKGB',
        json_format.MessageToJson(response))
