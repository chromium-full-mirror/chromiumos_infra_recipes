# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf import json_format

from PB.chromite.api.api import VersionGetRequest
from PB.chromite.api.api import VersionGetResponse

# pylint: disable=unused-import
from PB.recipe_modules.chromeos.cros_build_api.examples.set_api_return import SetReturnProperties as PROPERTIES

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_build_api',
]



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
  resp_json = json_format.MessageToJson(resp, preserving_proto_field_name=True)

  yield api.test(
      'basic', api.properties(expected_response_json=resp_json),
      api.cros_build_api.set_api_return('test step', 'VersionService/Get',
                                        resp_json))

  yield api.test(
      'step-failure', api.properties(expect_assertion=True),
      api.cros_build_api.set_api_return('test step', 'VersionService/Get',
                                        retcode=1))
