# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

import json

from PB.recipe_modules.chromeos.naming.tests.tests import \
    GetGenerationRequestTitleProperties
from PB.recipes.chromeos.paygen import PaygenProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/step',
    'naming',
]


PaygenRequest = PaygenProperties.PaygenRequest

PROPERTIES = GetGenerationRequestTitleProperties


def RunSteps(api, properties):
  paygen_request_dict = json.loads(properties.serialized_paygen_request)
  actual_title = api.naming.get_generation_request_title(paygen_request_dict)
  api.assertions.assertEqual(actual_title, properties.expected_url_title)


def GenTests(api):

  yield api.test(
      'Full-Unsigned-Minios',
      api.properties(
          serialized_paygen_request='{'
          '  "minios": true,'
          '  "fullUpdate": true,'
          '  "tgtUnsignedImage": {'
          '    "build": {'
          '      "version": "100.0.0", '
          '      "channel": "canary-channel"'
          '    }, '
          '    "imageType": "IMAGE_TYPE_TEST"'
          '  }'
          '}',
      ),
      api.properties(
          expected_url_title='Unsigned IMAGE_TYPE_TEST canary-channel, minios | Full (100.0.0)'
      ))

  yield api.test(
      'N2N-Unsigned-Minios',
      api.properties(
          serialized_paygen_request='{'
          '  "minios": true,'
          '  "tgtUnsignedImage": {'
          '    "build": {'
          '      "version": "100.0.0",'
          '      "channel": "canary-channel"'
          '    }, '
          '    "imageType": "IMAGE_TYPE_TEST"'
          '  },'
          '  "srcUnsignedImage": {'
          '    "build": {'
          '        "version": "100.0.0",'
          '        "channel": "canary-channel"'
          '    },'
          '    "imageType": "IMAGE_TYPE_TEST"'
          '  }'
          '}',
      ),
      api.properties(
          expected_url_title='Unsigned IMAGE_TYPE_TEST canary-channel, minios | Delta-N2N (100.0.0-100.0.0)'
      ))
