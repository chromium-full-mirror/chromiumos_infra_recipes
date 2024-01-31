# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from copy import deepcopy

from google.protobuf.json_format import MessageToDict

from PB.chromite.api.payload import Build
from PB.chromite.api.payload import DLCImage
from PB.chromite.api.payload import GenerationRequest
from PB.chromite.api.payload import SignedImage
from PB.chromite.api.payload import UnsignedImage
from PB.chromiumos.common import ImageType
from PB.recipe_modules.chromeos.naming.tests.tests import \
    BuildUrlTitleProperties
from PB.recipes.chromeos.paygen import PaygenProperties
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/step',
    'naming',
]


PaygenRequest = PaygenProperties.PaygenRequest

PROPERTIES = BuildUrlTitleProperties

BUILD_ID = 123456


def RunSteps(api, properties):
  with api.step.nest('setup'):
    paygen_request_dicts = []
    for paygen_request in properties.paygen_requests:
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
    api.assertions.assertEqual(actual_title, properties.expected_url_title)


def GenTests(api):

  yield api.test(
      'No-payloads',
      api.properties(expected_url_title='123456 | No paygen requests'),
  )

  yield api.test(
      'One-Full-Payload-Signed-Image',
      api.properties(
          BuildUrlTitleProperties(
              paygen_requests=[
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
                      )),
              ],
          )),
      api.properties(
          expected_url_title='123456 | Signed IMAGE_TYPE_RECOVERY canary-channel | Full (100.0.0)'
      ),
  )

  yield api.test(
      'One-Delta-Payload-Signed-Image',
      api.properties(
          BuildUrlTitleProperties(paygen_requests=[
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
              )
          ])),
      api.properties(
          expected_url_title='123456 | Signed IMAGE_TYPE_RECOVERY dev-channel | Delta (99.0.0-100.0.0)'
      ),
  )

  yield api.test(
      'One-Full-Payload-Unsigned-Image',
      api.properties(
          BuildUrlTitleProperties(
              paygen_requests=[
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
                      )),
              ],
          )),
      api.properties(
          expected_url_title='123456 | Unsigned IMAGE_TYPE_TEST canary-channel | Full (100.0.0)'
      ),
  )

  yield api.test(
      'One-Delta-Payload-Unsigned-Image',
      api.properties(
          BuildUrlTitleProperties(paygen_requests=[
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
              )
          ])),
      api.properties(
          expected_url_title='123456 | Unsigned IMAGE_TYPE_TEST canary-channel | Delta (99.0.0-100.0.0)'
      ),
  )

  yield api.test(
      'One-Full-Payload-DLC-Image',
      api.properties(
          BuildUrlTitleProperties(
              paygen_requests=[
                  PaygenRequest(
                      generation_request=GenerationRequest(
                          tgt_dlc_image=DLCImage(
                              build=Build(
                                  version='100.0.0',
                                  channel='canary-channel',
                              ), dlc_id='handwriting-zh'),
                          full_update=True,
                      )),
              ],
          )),
      api.properties(
          expected_url_title='123456 | DLC (handwriting-zh) canary-channel | Full (100.0.0)'
      ),
  )

  yield api.test(
      'One-Delta-Payload-DLC-Image',
      api.properties(
          BuildUrlTitleProperties(paygen_requests=[
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
              )
          ])),
      api.properties(
          expected_url_title='123456 | DLC (handwriting-zh) canary-channel | Delta (99.0.0-100.0.0)'
      ),
  )

  yield api.test(
      'Multiple-Full-DLC-Payloads-Same-Target-Version',
      api.properties(
          BuildUrlTitleProperties(paygen_requests=[
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
              ),
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
              ),
          ])),
      api.properties(expected_url_title='123456 | 2x DLC | Full (100.0.0)'),
  )

  yield api.test(
      'Multiple-Full-DLC-Payloads-Different-Target-Versions',
      api.properties(
          BuildUrlTitleProperties(paygen_requests=[
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
              ),
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
              ),
          ])),
      api.properties(
          expected_url_title='123456 | 2x DLC | Full (various versions)'),
  )

  yield api.test(
      'Multiple-Full-DLC-Payloads-Some-Full-Some-Delta',
      api.properties(
          BuildUrlTitleProperties(paygen_requests=[
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
              ),
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
              ),
          ])),
      api.properties(
          expected_url_title='123456 | 2x DLC | Some full, some delta'),
  )

  yield api.test(
      'Multiple-Full-DLC-Payloads-Different-Image-Types',
      api.properties(
          BuildUrlTitleProperties(paygen_requests=[
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
              ),
              PaygenRequest(
                  generation_request=GenerationRequest(
                      tgt_signed_image=SignedImage(
                          build=Build(
                              version='101.0.0',
                              channel='dev-channel',
                          ), image_type=ImageType.IMAGE_TYPE_BASE),
                      full_update=True),
              ),
          ])),
      api.properties(
          expected_url_title='123456 | 2 payloads, various image types | Full (various versions)'
      ),
  )

  yield api.test(
      'One-Full-MiniOS-Payload',
      api.properties(
          BuildUrlTitleProperties(
              paygen_requests=[
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
                      )),
              ],
          )),
      api.properties(
          expected_url_title='123456 | Signed IMAGE_TYPE_RECOVERY canary-channel, minios | Full (100.0.0)'
      ),
  )

  yield api.test(
      'One-Full-One-N2N-MiniOS-Payload',
      api.properties(
          BuildUrlTitleProperties(
              paygen_requests=[
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
                      )),
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
                      )),
              ],
          )),
      api.properties(
          expected_url_title='123456 | 2x Signed IMAGE_TYPE_RECOVERY canary-channel, minios | Some full, some delta'
      ),
  )

  yield api.test(
      'No-Target-Image',
      api.properties(
          BuildUrlTitleProperties(
              paygen_requests=[
                  PaygenRequest(
                      generation_request=GenerationRequest(full_update=True),
                  ),
              ],
          )),
      api.post_check(post_process.StepFailure, 'run'),
      status='FAILURE',
  )

  yield api.test(
      'No-Source-Image',
      api.properties(
          BuildUrlTitleProperties(
              paygen_requests=[
                  PaygenRequest(
                      generation_request=GenerationRequest(
                          tgt_signed_image=SignedImage(
                              build=Build(
                                  version='100.0.0',
                                  channel='canary-channel',
                              ),
                              image_type=ImageType.IMAGE_TYPE_RECOVERY,
                          ))),
              ],
          )),
      api.properties(
          expected_url_title='123456 | Signed IMAGE_TYPE_RECOVERY canary-channel | No src image found (?-100.0.0)'
      ),
  )
