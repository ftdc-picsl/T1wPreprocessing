FROM cookpa/hd-bet:0.3.0

ARG DOCKER_IMAGE_TAG="unknown"
ARG DOCKER_IMAGE_VERSION="unknown"

ARG GIT_REMOTE="unknown"
ARG GIT_COMMIT="unknown"

# Get c3d
COPY --from=pyushkevich/tk:2023b /tk/c3d/build/c3d /opt/bin/c3d

COPY scripts/* /opt/bin

LABEL maintainer="Philip A Cook (https://github.com/cookpa)"
LABEL description="Containerized pre-processing using HD-BET and c3d."
LABEL git.remote=$GIT_REMOTE
LABEL git.commit=$GIT_COMMIT

ENV GIT_REMOTE=$GIT_REMOTE
ENV GIT_COMMIT=$GIT_COMMIT
ENV DOCKER_IMAGE_TAG=$DOCKER_IMAGE_TAG
ENV DOCKER_IMAGE_VERSION=$DOCKER_IMAGE_VERSION

ENV PATH="/opt/bin:$PATH"

ENTRYPOINT ["/opt/bin/run.py"]
CMD ["-h"]
