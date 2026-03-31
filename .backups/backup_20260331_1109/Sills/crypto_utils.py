"""
密码加密工具
使用 Fernet 对称加密存储邮件密码
"""
import os
from typing import Optional


def get_crypto_key() -> bytes:
    """
    获取加密密钥

    从环境变量 MAIL_CRYPTO_KEY 获取。
    如果未设置，抛出异常。

    生成密钥方法:
        from cryptography.fernet import Fernet
        print(Fernet.generate_key().decode())

    Returns:
        加密密钥 (bytes)
    """
    key = os.environ.get('MAIL_CRYPTO_KEY')
    if not key:
        raise ValueError(
            "MAIL_CRYPTO_KEY environment variable not set. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return key.encode()


def encrypt_password(plain_password: str) -> str:
    """
    加密密码

    Args:
        plain_password: 明文密码

    Returns:
        加密后的密码字符串
    """
    from cryptography.fernet import Fernet
    f = Fernet(get_crypto_key())
    return f.encrypt(plain_password.encode()).decode()


def decrypt_password(encrypted_password: str) -> str:
    """
    解密密码

    Args:
        encrypted_password: 加密的密码

    Returns:
        解密后的明文密码
    """
    from cryptography.fernet import Fernet
    f = Fernet(get_crypto_key())
    return f.decrypt(encrypted_password.encode()).decode()


def generate_key() -> str:
    """
    生成新的加密密钥（用于初始化）

    Returns:
        新生成的密钥字符串
    """
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode()


if __name__ == "__main__":
    # 测试或生成密钥
    print("Generate a new MAIL_CRYPTO_KEY:")
    print(generate_key())