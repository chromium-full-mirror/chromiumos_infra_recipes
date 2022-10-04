# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from copy import deepcopy

from google.protobuf.json_format import MessageToDict

from recipe_engine import post_process
from recipe_engine.recipe_api import Property

from PB.chromite.api.payload import Build
from PB.chromite.api.payload import DLCImage
from PB.chromite.api.payload import GenerationRequest
from PB.chromite.api.payload import SignedImage
from PB.chromite.api.payload import UnsignedImage
from PB.chromiumos.common import ImageType
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
    # Recipes seems to forbid unhashable types (such as dicts) in props.
    # To avoid this issue, serialize the requests to strings.
    # The test will parse each string to a message, and then cast to dict.
    'serialized_paygen_requests':
        Property(kind=list, default=[],
                 help='Serialized PaygenRequests in the fake Paygen build.'),
    'expected_url_title':
        Property(kind=str, default=False,
                 help='The URL title that should be generated for the build.'),
}

BUILD_ID = 123456


def RunSteps(api, serialized_paygen_requests, expected_url_title):
  with api.step.nest('setup'):
    paygen_request_dicts = []
    for serialized_paygen_request in serialized_paygen_requests:
      paygen_request = PaygenRequest()
      paygen_request.ParseFromString(serialized_paygen_request)
      paygen_request_dict = MessageToDict(paygen_request)
      # It seems that this method of creating the dict
      # causes the GenerationRequest to be stored under 'generationRequest',
      # whereas it's supposed to be under 'generation_request'.
      if 'generationRequest' in paygen_request_dict:
        generation_request = deepcopy(paygen_request_dict['generationRequest'])
        paygen_request_dict['generation_request'] = generation_request
        del paygen_request_dict['generationRequest']
      paygen_request_dicts.append(paygen_request_dict)
  with api.step.nest('run'):
    actual_title = api.naming.get_paygen_build_title(BUILD_ID,
                                                     paygen_request_dicts)
  with api.step.nest('assert'):
    api.assertions.assertEqual(actual_title, expected_url_title)


def GenTests(api):

  yield api.test(
      'No-payloads',
      api.properties(expected_url_title='123456 | No paygen requests'),
      api.post_check(post_process.StatusSuccess))

  yield api.test(
      'One-Full-Payload-Signed-Image',
      api.properties(
          serialized_paygen_requests=[
              PaygenRequest(
                  generation_request=GenerationRequest(
                      tgt_signed_image=SignedImage(
                          build=Build(
                              version='100.0.0',
                              channel='canary-channel',
                          ),
                          image_type=ImageType.IMAGE_TYPE_RECOVERY,
                      ),
                      full_update=True,
                  )).SerializeToString(),
          ],
      ),
      api.properties(
          expected_url_title='123456 | Signed IMAGE_TYPE_RECOVERY canary-channel | Full (100.0.0)'
      ), api.post_check(post_process.StatusSuccess))

  yield api.test(
      'One-Delta-Payload-Signed-Image',
      api.properties(serialized_paygen_requests=[
          PaygenRequest(
              generation_request=GenerationRequest(
                  tgt_signed_image=SignedImage(
                      build=Build(
                          version='100.0.0',
                          channel='dev-channel',
                      ),
                      image_type=ImageType.IMAGE_TYPE_RECOVERY,
                  ),
                  src_signed_image=SignedImage(
                      build=Build(
                          version='99.0.0',
                      ),
                      image_type=ImageType.IMAGE_TYPE_RECOVERY,
                  ),
              ),
          ).SerializeToString()
      ]),
      api.properties(
          expected_url_title='123456 | Signed IMAGE_TYPE_RECOVERY dev-channel | Delta (99.0.0-100.0.0)'
      ), api.post_check(post_process.StatusSuccess))

  yield api.test(
      'One-Full-Payload-Unsigned-Image',
      api.properties(
          serialized_paygen_requests=[
              PaygenRequest(
                  generation_request=GenerationRequest(
                      tgt_unsigned_image=UnsignedImage(
                          build=Build(
                              version='100.0.0',
                              channel='canary-channel',
                          ),
                          image_type=ImageType.IMAGE_TYPE_TEST,
                      ),
                      full_update=True,
                  )).SerializeToString(),
          ],
      ),
      api.properties(
          expected_url_title='123456 | Unsigned IMAGE_TYPE_TEST canary-channel | Full (100.0.0)'
      ), api.post_check(post_process.StatusSuccess))

  yield api.test(
      'One-Delta-Payload-Unsigned-Image',
      api.properties(serialized_paygen_requests=[
          PaygenRequest(
              generation_request=GenerationRequest(
                  tgt_unsigned_image=UnsignedImage(
                      build=Build(
                          version='100.0.0',
                          channel='canary-channel',
                      ),
                      image_type=ImageType.IMAGE_TYPE_TEST,
                  ),
                  src_unsigned_image=UnsignedImage(
                      build=Build(
                          version='99.0.0',
                      ),
                      image_type=ImageType.IMAGE_TYPE_TEST,
                  ),
              ),
          ).SerializeToString()
      ]),
      api.properties(
          expected_url_title='123456 | Unsigned IMAGE_TYPE_TEST canary-channel | Delta (99.0.0-100.0.0)'
      ), api.post_check(post_process.StatusSuccess))

  yield api.test(
      'One-Full-Payload-DLC-Image',
      api.properties(
          serialized_paygen_requests=[
              PaygenRequest(
                  generation_request=GenerationRequest(
                      tgt_dlc_image=DLCImage(
                          build=Build(
                              version='100.0.0',
                              channel='canary-channel',
                          ), dlc_id='handwriting-zh'),
                      full_update=True,
                  )).SerializeToString(),
          ],
      ),
      api.properties(
          expected_url_title='123456 | DLC (handwriting-zh) canary-channel | Full (100.0.0)'
      ), api.post_check(post_process.StatusSuccess))

  yield api.test(
      'One-Delta-Payload-DLC-Image',
      api.properties(serialized_paygen_requests=[
          PaygenRequest(
              generation_request=GenerationRequest(
                  tgt_dlc_image=DLCImage(
                      build=Build(
                          version='100.0.0',
                          channel='canary-channel',
                      ), dlc_id='handwriting-zh'),
                  src_dlc_image=DLCImage(
                      build=Build(
                          version='99.0.0',
                      ), dlc_id='handwriting-zh'),
              ),
          ).SerializeToString()
      ]),
      api.properties(
          expected_url_title='123456 | DLC (handwriting-zh) canary-channel | Delta (99.0.0-100.0.0)'
      ), api.post_check(post_process.StatusSuccess))

  yield api.test(
      'Multiple-Full-DLC-Payloads-Same-Target-Version',
      api.properties(serialized_paygen_requests=[
          PaygenRequest(
              generation_request=GenerationRequest(
                  tgt_dlc_image=DLCImage(
                      build=Build(
                          version='100.0.0',
                          channel='canary-channel',
                      ), image_type=ImageType.IMAGE_TYPE_DLC,
                      dlc_id='handwriting-zh'),
                  full_update=True,
              ),
          ).SerializeToString(),
          PaygenRequest(
              generation_request=GenerationRequest(
                  tgt_dlc_image=DLCImage(
                      build=Build(
                          version='100.0.0',
                          channel='dev-channel',
                      ), image_type=ImageType.IMAGE_TYPE_DLC,
                      dlc_id='handwriting-au'),
                  full_update=True,
              ),
          ).SerializeToString(),
      ]), api.properties(expected_url_title='123456 | 2x DLC | Full (100.0.0)'),
      api.post_check(post_process.StatusSuccess))

  yield api.test(
      'Multiple-Full-DLC-Payloads-Different-Target-Versions',
      api.properties(serialized_paygen_requests=[
          PaygenRequest(
              generation_request=GenerationRequest(
                  tgt_dlc_image=DLCImage(
                      build=Build(
                          version='100.0.0',
                          channel='canary-channel',
                      ), image_type=ImageType.IMAGE_TYPE_DLC,
                      dlc_id='handwriting-zh'),
                  full_update=True,
              ),
          ).SerializeToString(),
          PaygenRequest(
              generation_request=GenerationRequest(
                  tgt_dlc_image=DLCImage(
                      build=Build(
                          version='101.0.0',
                          channel='dev-channel',
                      ), image_type=ImageType.IMAGE_TYPE_DLC,
                      dlc_id='handwriting-au'),
                  full_update=True,
              ),
          ).SerializeToString(),
      ]),
      api.properties(
          expected_url_title='123456 | 2x DLC | Full (various versions)'),
      api.post_check(post_process.StatusSuccess))

  yield api.test(
      'Multiple-Full-DLC-Payloads-Some-Full-Some-Delta',
      api.properties(serialized_paygen_requests=[
          PaygenRequest(
              generation_request=GenerationRequest(
                  tgt_dlc_image=DLCImage(
                      build=Build(
                          version='100.0.0',
                          channel='canary-channel',
                      ), image_type=ImageType.IMAGE_TYPE_DLC,
                      dlc_id='handwriting-zh'),
                  full_update=True,
              ),
          ).SerializeToString(),
          PaygenRequest(
              generation_request=GenerationRequest(
                  tgt_dlc_image=DLCImage(
                      build=Build(
                          version='101.0.0',
                          channel='dev-channel',
                      ), image_type=ImageType.IMAGE_TYPE_DLC,
                      dlc_id='handwriting-au'),
                  src_dlc_image=DLCImage(
                      build=Build(
                          version='99.0.0',
                      ), dlc_id='handwriting-zh'),
              ),
          ).SerializeToString(),
      ]),
      api.properties(
          expected_url_title='123456 | 2x DLC | Some full, some delta'),
      api.post_check(post_process.StatusSuccess))

  yield api.test(
      'Multiple-Full-DLC-Payloads-Different-Image-Types',
      api.properties(serialized_paygen_requests=[
          PaygenRequest(
              generation_request=GenerationRequest(
                  tgt_dlc_image=DLCImage(
                      build=Build(
                          version='100.0.0',
                          channel='canary-channel',
                      ), image_type=ImageType.IMAGE_TYPE_DLC,
                      dlc_id='handwriting-zh'),
                  full_update=True,
              ),
          ).SerializeToString(),
          PaygenRequest(
              generation_request=GenerationRequest(
                  tgt_signed_image=SignedImage(
                      build=Build(
                          version='101.0.0',
                          channel='dev-channel',
                      ), image_type=ImageType.IMAGE_TYPE_BASE),
                  full_update=True),
          ).SerializeToString(),
      ]),
      api.properties(
          expected_url_title='123456 | 2 payloads, various image types | Full (various versions)'
      ), api.post_check(post_process.StatusSuccess))

  yield api.test(
      'One-Full-MiniOS-Payload',
      api.properties(
          serialized_paygen_requests=[
              PaygenRequest(
                  generation_request=GenerationRequest(
                      tgt_signed_image=SignedImage(
                          build=Build(
                              version='100.0.0',
                              channel='canary-channel',
                          ),
                          image_type=ImageType.IMAGE_TYPE_RECOVERY,
                      ),
                      full_update=True,
                      minios=True,
                  )).SerializeToString(),
          ],
      ),
      api.properties(
          expected_url_title='123456 | Signed IMAGE_TYPE_RECOVERY canary-channel, minios | Full (100.0.0)'
      ), api.post_check(post_process.StatusSuccess))

  yield api.test(
      'One-Full-One-N2N-MiniOS-Payload',
      api.properties(
          serialized_paygen_requests=[
              PaygenRequest(
                  generation_request=GenerationRequest(
                      tgt_signed_image=SignedImage(
                          build=Build(
                              version='100.0.0',
                              channel='canary-channel',
                          ),
                          image_type=ImageType.IMAGE_TYPE_RECOVERY,
                      ),
                      full_update=True,
                      minios=True,
                  )).SerializeToString(),
              PaygenRequest(
                  generation_request=GenerationRequest(
                      tgt_signed_image=SignedImage(
                          build=Build(
                              version='100.0.0',
                              channel='canary-channel',
                          ),
                          image_type=ImageType.IMAGE_TYPE_RECOVERY,
                      ),
                      src_signed_image=SignedImage(
                          build=Build(
                              version='100.0.0',
                              channel='canary-channel',
                          ),
                          image_type=ImageType.IMAGE_TYPE_RECOVERY,
                      ),
                      minios=True,
                  )).SerializeToString(),
          ],
      ),
      api.properties(
          expected_url_title='123456 | 2x Signed IMAGE_TYPE_RECOVERY canary-channel, minios | Some full, some delta'
      ), api.post_check(post_process.StatusSuccess))

  yield api.test(
      'No-Target-Image',
      api.properties(
          serialized_paygen_requests=[
              PaygenRequest(
                  generation_request=GenerationRequest(full_update=True),
              ).SerializeToString(),
          ],
      ), api.post_check(post_process.StepFailure, 'run'))

  yield api.test(
      'No-Source-Image',
      api.properties(
          serialized_paygen_requests=[
              PaygenRequest(
                  generation_request=GenerationRequest(
                      tgt_signed_image=SignedImage(
                          build=Build(
                              version='100.0.0',
                              channel='canary-channel',
                          ),
                          image_type=ImageType.IMAGE_TYPE_RECOVERY,
                      ))).SerializeToString(),
          ],
      ),
      api.properties(
          expected_url_title='123456 | Signed IMAGE_TYPE_RECOVERY canary-channel | No src image found (?-100.0.0)'
      ), api.post_check(post_process.StatusSuccess))
