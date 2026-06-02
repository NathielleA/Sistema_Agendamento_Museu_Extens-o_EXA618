from pymongo import MongoClient
import os

MONGODB_URI = os.environ.get("MONGODB_URI")

client = MongoClient(MONGODB_URI)

db = client["museu"]

regras = [
    {
        "titulo": "Horário de funcionamento",
        "conteudo": "O museu está aberto à visitação de segunda a sexta de 8:00 às 12:00; e de 14:00 às 18:00 h.",
        "observacao": "Nas edições do Programa Domingo Tem Museu, uma parceria entre a CIA CUCA de Teatro e o MRA o funcionamento se dá em regime especial, no primeiro domingo de cada mês de 9:00 às 13:00 h.",
        "ativo": True
    },
    {
        "titulo": "Normas de funcionamento",
        "conteudo": "O Museu Regional de Arte (MRA) tem como principal finalidade atender à comunidade, oferecendo a esta mostras e exposições com o melhor das artes brasileira e internacional. Mas para garantir a proteção e o cuidado com as obras, patrimônio de toda a sociedade feirense e brasileira, o Museu adota algumas normas para a realização das visitas. Conheça estas normas para poder aproveitar ao máximo a experiência de desfrutar deste espaço de cultura.",
        "ativo": True
    },
    {
        "titulo": "Normas de visitação",
        "conteudo": "Os usuários do MRA deverão observar as seguintes normas de visitação:"
            "Não é permitido correr nos espaços de exposição do MRA;"
            "Não é permitido tocar nas obras, salvo quando estas forem concebidas para tal finalidade;"
            "Não é permitida a danificação de obras ou equipamentos e estruturas expositivas, sob pena do responsável pelo dano ser devidamente identificado e sujeito ao pagamento de restauro ou de custos de reparação, sem prejuízo das demais sansões legais provenientes de danos ao patrimônio público;"
            "Não é permitido fumar em qualquer das dependências do Museu;"
            "Não é permitido fotografar ou filmar nas áreas de exposição, sem autorização prévia da coordenação ou do museólogo responsável;"
            "Não é permitida a entrada de visitantes em áreas restritas, tais como sala de museologia, reserva técnica ou gabinete da coordenação, salvo quando devidamente autorizados e acompanhados por pessoal do corpo técnico do Museu."
    },
    {
        "titulo": "Restrições de acesso",
        "conteudo": "Visando assegurar a salvaguarda do patrimônio do museu de seus usuários, admitem-se as seguintes restrições à entrada:"
            "É proibido entrar, sem autorização prévia do coordenador do Museu ou do museólogo encarregado e/ou da tutela de um destes, com equipamento vídeo ou fotográfico;"
            "É interdita a entrada de pessoas com malas ou outros objetos de grandes dimensões, que devem ser deixadas na área de recepção;"
            "É proibida a entrada de animais dentro dos espaços do museu, exceto no caso de cães- guias que acompanhem pessoas portadoras de deficiência visual;"
            "Caso o visitante pretenda guardar na recepção objetos que repute de elevado valor, estes devem ser declarados e identificados pelo visitante;"
            "A recepção pode recusar-se a guardar objetos pessoais do visitante, caso se verifique que estes não podem ser guardados."
    }
]

institucional = [
    {
        "tipo": "sobre_museu",
        "titulo": "Sobre o Museu",
        "conteudo": "Texto sobre o museu."
    },
    {
        "tipo": "sobre_uefs",
        "titulo": "Sobre a UEFS",
        "conteudo": "Texto sobre a universidade."
    }
]

db.regras.insert_many(regras)
db.institucional.insert_many(institucional)

print("Seed executado com sucesso.")