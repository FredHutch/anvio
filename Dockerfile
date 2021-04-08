# To start a build in an absolutely pristine Docker environment you can use the following
# to clean up your docker (although please note that it will remove all existing containers
# and cached states):
#
#     docker rmi --force $(docker images -a --filter=dangling=true -q)
#     docker rm --force $(docker ps --filter=status=exited --filter=status=created -q)
#     docker system prune --force -a
#
# after that, you can start the build with the following:
#
#     BUILDKIT_PROGRESS=plain docker build -t meren/anvio:$ANVIO_VERSION .
#

FROM continuumio/miniconda3:4.9.2
ENV ANVIO_VERSION "7"

RUN conda config --env --add channels bioconda && \
    conda config --env --add channels conda-forge && \
    conda create -n anvioenv python=3.6 && \
    conda install -y nano

# Activate environment
ENV PATH /opt/conda/envs/anvioenv/bin:$PATH
ENV CONDA_DEFAULT_ENV anvioenv
ENV CONDA_PREFIX /opt/conda/envs/anvioenv

RUN echo "conda activate anvioenv" >> ~/.bashrc

RUN conda install -y conda-build && \
    conda install -y conda-verify

COPY conda-recipe /tmp/conda-recipe

# build and install anvio-minimal
RUN conda-build /tmp/conda-recipe/anvio-minimal && \
    conda index /opt/conda/envs/anvioenv/conda-bld/ && \
    conda install -c file:///opt/conda/envs/anvioenv/conda-bld/ anvio-minimal=$ANVIO_VERSION && \
    conda build purge-all
RUN conda-build /tmp/conda-recipe/anvio && \
    conda index /opt/conda/envs/anvioenv/conda-bld/ && \
    conda install -c file:///opt/conda/envs/anvioenv/conda-bld/ anvio=$ANVIO_VERSION && \
    conda build purge-all && \
    conda install metabat2 das_tool


# Install CONCOCT
RUN apt-get update && apt-get install -qq build-essential libgsl0-dev bedtools mummer samtools perl libssl-dev && \
    conda install cython && \
    pip install https://github.com/BinPro/CONCOCT/archive/1.1.0.tar.gz && \
    pip install git+https://github.com/edgraham/BinSanity.git


# Install MAXBIN2 (installing fraggenescan will require cpanm, and we also need IDBA-UD)
RUN conda install -c bioconda perl-app-cpanminus && \
    cpanm --self-upgrade --sudo && \
    conda install -c bioconda idba && \
    cd /opt && wget https://downloads.sourceforge.net/project/fraggenescan/FragGeneScan1.31.tar.gz && tar zxf FragGeneScan1.31.tar.gz && cd FragGeneScan1.31 && make clean && make && \
    cpanm install LWP::Simple
ENV PERL5LIB /opt/conda/envs/anvioenv/lib/5.26.2/:/opt/conda/envs/anvioenv/lib/site_perl/5.26.2/:$PERL5LIB
RUN cd /opt && wget https://downloads.sourceforge.net/project/maxbin2/MaxBin-2.2.7.tar.gz && tar zxf MaxBin-2.2.7.tar.gz && cd MaxBin-2.2.7/src && make && \
    echo 'export PATH=/opt/FragGeneScan1.31:$PATH' >> ~/.bashrc
RUN echo 'export PATH=/opt/MaxBin-2.2.7:$PATH' >> ~/.bashrc

# Install some helper tools
RUN pip install virtualenv && \
    apt-get install vim util-linux -yy && \
    Rscript -e 'install.packages(c("optparse"), repos="https://cran.rstudio.com")' && \
    rm -rf /var/lib/apt/lists/* && \
    apt-get -y clean

# Cutify the environment
RUN echo "export PS1=\"\[\e[0m\e[47m\e[1;30m\] :: anvi'o v$ANVIO_VERSION :: \[\e[0m\e[0m \[\e[1;34m\]\]\w\[\e[m\] \[\e[1;32m\]>>>\[\e[m\] \[\e[0m\]\"" >> /root/.bashrc
RUN mkdir -p /work
WORKDIR /work

CMD /bin/bash -l

# To test the build, you can run this:
#
# docker run --rm -it -v `pwd`:`pwd` -w `pwd` -p 8080:8080 meren/anvio:test-build
