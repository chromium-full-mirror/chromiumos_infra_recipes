# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json

from recipe_engine import post_process
from recipe_engine.recipe_api import Property

from PB.recipes.chromeos.paygen import PaygenProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/step',
    'naming',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PaygenRequest = PaygenProperties.PaygenRequest

PROPERTIES = {
    'serialized_paygen_request':
        Property(kind=str, default=False, help='Serialized PaygenRequest.'),
    'expected_url_title':
        Property(
            kind=str, default=False,
            help='The URL title that should be generated for the request.'),
}


def RunSteps(api, serialized_paygen_request, expected_url_title):
  paygen_request_dict = json.loads(serialized_paygen_request)
  actual_title = api.naming.get_generation_request_title(paygen_request_dict)
  api.assertions.assertEqual(actual_title, expected_url_title)


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
      ), api.post_check(post_process.StatusSuccess))

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
      ), api.post_check(post_process.StatusSuccess))
