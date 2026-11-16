# Face detection resource

`haarcascade_frontalface_default.xml` is the unmodified OpenCV 4.12.0 resource:
https://github.com/opencv/opencv/blob/4.12.0/data/haarcascades/haarcascade_frontalface_default.xml

SHA256: `0f7d4527844eb514d4a4948e822da90fbb16a34a0bbbbc6adc6498747a5aafb0`.
The original license and attribution are retained in the XML header.
It is packaged with the backend to avoid depending on an installation's optional
OpenCV data directory. No model is downloaded at runtime.

This model checks for one frontal face. It does not establish identity or classify
image safety; verification is handled separately by Smile ID.
