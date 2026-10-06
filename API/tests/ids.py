"""IDs fixos dos usuarios falsos usados nos testes.

Desde o B20 os usuarios ficam na tabela `medico` e paciente/consulta tem FK
para ela: os IDs precisam ser UUIDs e existir no banco. O conftest cadastra
todos os IDs abaixo no banco de cada teste.
"""
TEST_USER_ID = "00000000-0000-4000-8000-000000000001"
DOCTOR_A = "00000000-0000-4000-8000-00000000000a"
DOCTOR_B = "00000000-0000-4000-8000-00000000000b"
ADMIN_1 = "00000000-0000-4000-8000-0000000000ad"

# (id, email, perfis) cadastrados pelo conftest
USUARIOS_DE_TESTE = [
    (TEST_USER_ID, "doctor@example.com", ["administrador", "medico"]),
    (DOCTOR_A, "doctor-a@example.com", ["medico"]),
    (DOCTOR_B, "doctor-b@example.com", ["medico"]),
    (ADMIN_1, "admin-1@example.com", ["administrador"]),
]
