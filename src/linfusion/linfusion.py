from diffusers.models.attention_processor import Attention
from diffusers import ModelMixin, ConfigMixin
import functools

from .attention import GeneralizedLinearAttention


model_dict = {
    "runwayml/stable-diffusion-v1-5": "Yuanshi/LinFusion-1-5",
    "stablediffusionapi/realistic-vision-v51": "Yuanshi/LinFusion-1-5",
    "Lykon/dreamshaper-8": "Yuanshi/LinFusion-1-5",
}


def replace_submodule(model, module_name, new_submodule):
    path, attr = module_name.rsplit(".", 1)
    parent_module = functools.reduce(getattr, path.split("."), model)
    setattr(parent_module, attr, new_submodule)


class LinFusion(ModelMixin, ConfigMixin):
    def __init__(self, modules_list, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self.modules_dict = {}
        self.register_to_config(modules_list=modules_list)

        for i, attention_config in enumerate(modules_list):
            dim_n = attention_config["dim_n"]
            heads = attention_config["heads"]
            projection_mid_dim = attention_config["projection_mid_dim"]
            linear_attention = GeneralizedLinearAttention(
                query_dim=dim_n,
                out_dim=dim_n,
                dim_head=dim_n // heads,
                projection_mid_dim=projection_mid_dim,
            )
            self.add_module(f"{i}", linear_attention)
            self.modules_dict[attention_config["module_name"]] = linear_attention

    @classmethod
    def get_default_config(
        cls,
        pipeline=None,
        unet=None,
    ):
        """
        Get the default configuration for the LinFusion model.
        (The `projection_mid_dim` is same as the `query_dim` by default.)
        """
        assert unet is not None or pipeline.unet is not None
        unet = unet or pipeline.unet
        modules_list = []
        for module_name, module in unet.named_modules():
            if not isinstance(module, Attention):
                continue
            if "attn1" not in module_name:
                continue
            dim_n = module.to_q.weight.shape[0]
            # modules_list.append((module_name, dim_n, module.heads))
            modules_list.append(
                {
                    "module_name": module_name,
                    "dim_n": dim_n,
                    "heads": module.heads,
                    "projection_mid_dim": None,
                }
            )
        return {"modules_list": modules_list}

    @classmethod
    def construct_for(
        cls,
        pipeline=None,
        unet=None,
        load_pretrained=True,
        pretrained_model_name_or_path=None,
    ) -> "LinFusion":
        """
        Construct a LinFusion object for the given pipeline.
        """
        assert unet is not None or pipeline.unet is not None
        unet = unet or pipeline.unet
        if load_pretrained:
            # Load from pretrained
            pipe_name_path = pipeline._internal_dict._name_or_path
            if not pretrained_model_name_or_path:
                pretrained_model_name_or_path = model_dict.get(pipe_name_path, None)
                if pretrained_model_name_or_path:
                    print(
                        f"Matching LinFusion '{pretrained_model_name_or_path}' for pipeline '{pipe_name_path}'."
                    )
                else:
                    raise Exception(
                        f"LinFusion not found for pipeline [{pipe_name_path}], please provide the path."
                    )
            linfusion = (
                LinFusion.from_pretrained(pretrained_model_name_or_path)
                .to(pipeline.device)
                .to(pipeline.dtype)
            )
        else:
            # Create from scratch without pretrained parameters
            default_config = LinFusion.get_default_config(pipeline)
            linfusion = (
                LinFusion(**default_config).to(pipeline.device).to(pipeline.dtype)
            )
        linfusion.mount_to(unet)
        return linfusion

    def mount_to(self, unet) -> None:
        """
        Mounts the modules in the `modules_dict` to the given `pipeline`.
        """
        for module_name, module in self.modules_dict.items():
            replace_submodule(unet, module_name, module)
