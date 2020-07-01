define HELP_MSG
Usage:
	make help                   show this message
	make jupyter-base-env       build base environment docker image on the fly and run jupyter notebook inside its container
endef
export HELP_MSG
PWD:=$(shell pwd)
include not_shared/base.env

jupyter-base-env_command=touch $(sibling_docker_env_file); \
    docker run \
        -it \
        --rm  \
        --name miniconda3_container03 \
        -p $(vm_Jupyter_port):8888 \
        -v $(PWD)/../:/workspace:rw \
        -v /usr/bin/docker:/usr/bin/docker \
        -v /var/run/docker.sock:/var/run/docker.sock \
        continuumio/miniconda3 \
        /bin/bash -c 'ls -la /workspace \
        && export CONDA_ENV_NAME=azure_devito_control_plane_conda_env \
        && /opt/conda/bin/conda env create -q -n $$CONDA_ENV_NAME -f /workspace/notebooks/azure_devito_conda_dep_file_control_plane.yml \
        && export PATH=/opt/conda/envs/$$CONDA_ENV_NAME/bin/:/opt/conda/bin:$$PATH \
        && export in_container_sibling_docker_env_file='/workspace/notebooks/$(sibling_docker_env_file)' \
        && dotenv --file $$in_container_sibling_docker_env_file set 'DOCKER_CONTAINER_MOUNT_POINT' $(PWD) \
        && /opt/conda/bin/conda install --name $$CONDA_ENV_NAME jupyter -y --quiet \
        && /opt/conda/envs/$$CONDA_ENV_NAME/bin/jupyter notebook --notebook-dir=/workspace --ip=0.0.0.0 --port=8888 --no-browser --allow-root '



help:
	@echo "$$HELP_MSG" 

jupyter-base-env:
	@$(jupyter-base-env_command) 

    
    
.PHONY: help 

    