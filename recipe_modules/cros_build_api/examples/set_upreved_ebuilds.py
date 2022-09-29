# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json

from google.protobuf import json_format

from PB.chromite.api.packages import UprevVersionedPackageRequest
from PB.chromite.api.packages import UprevVersionedPackageResponse

# pylint: disable=unused-import
from PB.recipe_modules.chromeos.cros_build_api.examples.set_api_return import SetReturnProperties as PROPERTIES

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_build_api',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api, properties):
  with api.step.nest('test step'):
    api.assertions.assertEqual(
        api.cros_build_api.PackageService.UprevVersionedPackage(
            UprevVersionedPackageRequest()),
        json_format.Parse(properties.expected_response_json,
                          UprevVersionedPackageResponse(),
                          ignore_unknown_fields=True))


def GenTests(api):
  resp = UprevVersionedPackageResponse()
  r1 = resp.responses.add()
  e1 = r1.modified_ebuilds.add()
  e1.path = '[CLEANUP]/chromiumos_workspace/src/overlay/foo.ebuild'
  r1.version = '1.2.3'
  r1.additional_commit_info = 'additional info to be rendered on uprev cl.'

  # TODO(b/217973414): Replace with MessageToJson once we don't need to
  # fix the separator spacing between py2 and py3 MessageToJson.
  resp_json = json.dumps(
      json_format.MessageToDict(resp, preserving_proto_field_name=True),
      separators=(',', ':'), sort_keys=True)
  yield api.test(
      'single-ebuild', api.properties(expected_response_json=resp_json),
      api.cros_build_api.set_upreved_ebuilds(['src/overlay/foo.ebuild']))
