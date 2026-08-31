import { useNavigate } from "react-router-dom";

import Button from "../../components/ui/Button";

function Error() {

    const navigate = useNavigate();

    const handleTakeMeBack = () => {
        navigate(`/views/landing`);
    };
    return (
        <div className="w-full h-screen flex flex-col items-center justify-center gap-10">
            <h1 className="text-6xl font-bold text-center m-0">
                Page not found!
            </h1>
            <Button size="lg" onClick={handleTakeMeBack}>
                Take me back!
            </Button>
        </div>
    );
}

export default Error;
