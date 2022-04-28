# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import json

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_build_api',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

from google.protobuf import json_format

from PB.chromite.api.api import VersionGetRequest
from PB.chromite.api.api import VersionGetResponse
# pylint: disable=unused-import
from PB.recipe_modules.chromeos.cros_build_api.examples.set_api_return import (
    SetReturnProperties as PROPERTIES)


def RunSteps(api, properties):
  with api.step.nest('test step'):
    if properties.expect_assertion:
      api.assertions.assertRaises(api.step.StepFailure,
                                  api.cros_build_api.VersionService.Get,
                                  VersionGetRequest())
    else:
      api.assertions.assertEqual(
          api.cros_build_api.VersionService.Get(VersionGetRequest()),
          json_format.Parse(properties.expected_response_json,
                            VersionGetResponse(), ignore_unknown_fields=True))


def GenTests(api):
  resp = VersionGetResponse()
  resp.version.minor = 5555
  resp.version.bug = 5555
  # TODO(b/217973414): Replace with MessageToJson once we don't need to
  # fix the separator spacing between py2 and py3 MessageToJson.
  resp_json = json.dumps(
      json_format.MessageToDict(resp, preserving_proto_field_name=True),
      separators=(',', ':'), sort_keys=True)

  yield api.test(
      'basic', api.properties(expected_response_json=resp_json),
      api.cros_build_api.set_api_return('test step', 'VersionService/Get',
                                        resp_json))

  yield api.test(
      'step-failure', api.properties(expect_assertion=True),
      api.cros_build_api.set_api_return('test step', 'VersionService/Get',
                                        retcode=1))
